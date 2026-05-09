# -*- coding: utf-8 -*-

import re
import json
import base64
from pathlib import Path

from action.main import ActionManager
from observatory.agent_runtime import (
    AgentConfig,
    AgentRuntime,
    LLMGateway,
    _attachment_summary,
    _compact_object,
    _safe_read_json,
    _public_object_row,
    _public_tool_result,
    _clean_reply_text,
    _clean_thought_text,
    _read_jsonl_tail,
    _sanitize_llm_visible_text,
    _sanitize_object_display_text,
)


def _message_payload(text: str, *, group_id: str = "10001", user_id: str = "20002", message_id: str = "msg_1") -> dict:
    return {
        "adapter": "napcat_qq",
        "post_type": "message",
        "message_type": "group",
        "group_id": group_id,
        "user_id": user_id,
        "message_id": message_id,
        "sender": {"card": "银子"},
        "message": [{"type": "text", "data": {"text": text}}],
    }
def test_agent_public_projection_removes_debug_sequence_texture():
    raw = "{我 + 想 + 查 + 天气 + punish_signal:4.0} || {HTTP Error 502: Bad Gateway}"

    assert _sanitize_object_display_text(raw, max_chars=220) == "我想查天气"

    internal = _compact_object(
        {
            "ref_object_id": "st_000123",
            "ref_object_type": "st",
            "item_id": "spi_abc",
            "display": raw,
            "er": 1.0,
            "ev": 2.0,
            "cp_abs": 3.0,
        }
    )
    public = _public_object_row(internal)

    assert internal["id"] == "st_000123"
    assert public["id"].startswith("pa_st_")
    assert public["display"] == "我想查天气"
    assert "punish_signal" not in public["full_display"]
    assert "+" not in public["full_display"]
    assert "||" not in public["full_display"]


def test_agent_public_tool_result_hides_raw_provider_errors():
    public = _public_tool_result(
        {
            "tool": "weather",
            "ok": False,
            "latency_ms": 123,
            "output": {"error": "HTTP Error 502: Bad Gateway", "location": "上海"},
        },
        max_summary_chars=220,
    )

    assert public["summary"] == "天气工具这次没有成功返回 上海 的结果，我需要稍后重试或换一种查询方式。"
    assert "HTTP Error" not in str(public)
    assert "Bad Gateway" not in str(public)


def test_napcat_event_normalizes_private_and_group_targets():
    runtime = _runtime_for_flow([], soft=2, hard=3)

    private = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": 20002,
            "sender": {"nickname": "银子"},
            "message": [{"type": "text", "data": {"text": "你好"}}],
        }
    )
    group = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "group",
            "group_id": 10001,
            "user_id": 20002,
            "sender": {"card": "银子"},
            "message": [{"type": "at", "data": {"qq": "PA"}}, {"type": "text", "data": {"text": " 看这里"}}],
        }
    )

    assert private["conversation_id"] == "private:20002"
    assert private["reply_target"]["message_type"] == "private"
    assert private["reply_target"]["user_id"] == "20002"
    assert group["conversation_id"] == "group:10001"
    assert group["reply_target"]["message_type"] == "group"
    assert group["reply_target"]["group_id"] == "10001"
    assert "pa" in group["mentions"]
    assert private["target_label"] == "私聊 银子 (20002)"
    assert group["target_label"] == "群聊 10001 / 银子 (20002)"


def test_napcat_reply_segment_keeps_inline_quote_text():
    runtime = _runtime_for_flow([], soft=1, hard=1)

    normalized = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子"},
            "message": [
                {"type": "reply", "data": {"id": "123", "text": "上一句内容"}},
                {"type": "text", "data": {"text": " 我回复这个"}},
            ],
        }
    )

    assert "引用消息(123)" in normalized["text"]
    assert "上一句内容" in normalized["text"]
    assert "我回复这个" in normalized["text"]
    assert normalized["raw_event_preview"]["message_segments"][0]["data"]["id"] == "123"


def test_napcat_reply_segment_fetches_get_msg_when_text_missing(monkeypatch, tmp_path):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.qq_napcat_http_url = "http://127.0.0.1:3000"
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps(
                {
                    "status": "ok",
                    "data": {
                        "sender": {"nickname": "银子", "user_id": "200020002"},
                        "message": [{"type": "text", "data": {"text": "被引用内容"}}],
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        captured["timeout"] = timeout
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)
    normalized = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "测试者"},
            "message": [
                {"type": "reply", "data": {"id": "123"}},
                {"type": "text", "data": {"text": " 继续说"}},
            ],
        }
    )

    assert captured["url"].endswith("/get_msg")
    assert captured["body"] == {"message_id": "123"}
    assert captured["timeout"] <= 1.5
    assert "引用消息(123)：银子(200020002): 被引用内容" in normalized["text"]
    assert "继续说" in normalized["text"]


def test_napcat_forward_segment_uses_inline_nodes_and_group_history():
    runtime = _runtime_for_flow([], soft=1, hard=1)

    normalized = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "group",
            "group_id": "10001",
            "user_id": "200020002",
            "sender": {"card": "银子"},
            "message_id": "msg_forward",
            "message": [
                {
                    "type": "forward",
                    "data": {
                        "id": "forward-1",
                        "content": [
                            {
                                "type": "node",
                                "data": {
                                    "nickname": "银子",
                                    "user_id": "200020002",
                                    "content": [{"type": "text", "data": {"text": "第一句"}}],
                                },
                            },
                            {
                                "type": "node",
                                "data": {
                                    "nickname": "群友",
                                    "content": [{"type": "text", "data": {"text": "第二句"}}],
                                },
                            },
                        ],
                    },
                }
            ],
        }
    )
    runtime._remember_adapter_group_history(normalized, gate_stage="unit")

    assert "转发聊天记录(forward-1)" in normalized["text"]
    assert "1. 银子(200020002): 第一句" in normalized["text"]
    assert "2. 群友: 第二句" in normalized["text"]
    assert runtime.state["adapter_group_history"]["group:10001"][-1]["text"] == normalized["text"]


def test_napcat_forward_segment_fetches_get_forward_msg(monkeypatch, tmp_path):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.qq_napcat_http_url = "http://127.0.0.1:3000"
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps(
                {
                    "status": "ok",
                    "data": {
                        "messages": [
                            {
                                "type": "node",
                                "data": {
                                    "nickname": "A",
                                    "content": [{"type": "text", "data": {"text": "转发里的第一条"}}],
                                },
                            },
                            {
                                "type": "node",
                                "data": {
                                    "nickname": "B",
                                    "content": [{"type": "text", "data": {"text": "转发里的第二条"}}],
                                },
                            },
                        ]
                    },
                },
                ensure_ascii=False,
            ).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)
    normalized = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子"},
            "message": [{"type": "forward", "data": {"id": "forward-x"}}],
        }
    )

    assert captured["url"].endswith("/get_forward_msg")
    assert captured["body"] == {"id": "forward-x", "message_id": "forward-x"}
    assert "转发聊天记录(forward-x)" in normalized["text"]
    assert "A: 转发里的第一条" in normalized["text"]
    assert "B: 转发里的第二条" in normalized["text"]


def test_reply_decision_without_reply_text_is_not_public_fallback():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    packet = runtime.build_prompt_packet(reports=[])

    normalized = runtime._normalize_llm_payload(
        {
            "thought": "我又往下想了一层，现在这条线索比刚才更清楚了一点。",
            "decision": "reply",
            "reply_text": "",
            "tool_calls": [],
            "why": "unit missing reply text",
        },
        fallback_packet=packet,
        thought_index=1,
        user_text="晚上好",
    )

    assert normalized["decision"] == "continue_thinking"
    assert normalized["reply_text"] == ""
    assert "reply_missing_text" in normalized["quality_flags"]
    assert "我又往下想了一层" not in normalized["reply_text"]


def test_local_fallback_after_first_step_sleeps_without_public_diagnostics():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    packet = runtime.build_prompt_packet(reports=[])

    fallback = runtime._fallback_thought(
        user_text=(
            "当前对话框内容信息：\n"
            "User 17:14:47 在嘛?\n"
            "PA 17:15:38 在呀，银子。怎么啦？\n"
            "当前对话中最新消息:\n发送者: PA\n可见回复已发送成功"
        ),
        packet=packet,
        thought_index=1,
    )

    assert fallback["decision"] == "sleep"
    assert fallback["reply_text"] == ""
    assert "我又往下想了一层" not in fallback["thought"]
    assert "最醒目的线索" not in str(fallback)


def test_thought_and_reply_sanitizers_remove_old_diagnostic_template():
    raw = (
        "我又往下想了一层，现在这条线索比刚才更清楚了一点。"
        "现在最醒目的线索落在“在呀，银子。怎么啦？”附近。"
        "我也会把刚才被带起的记忆线索先贴在旁边：银子怎么啦。"
        "同时有一点压力感在推着我整理。如果还没有足够可靠的依据，我会继续保持克制。"
        "我已经回复过了，先停一下。"
    )

    thought = _clean_thought_text(raw)
    reply = _clean_reply_text(raw)
    visible = _sanitize_llm_visible_text(raw, max_chars=600)

    for value in (thought, reply, visible):
        assert "我又往下想了一层" not in value
        assert "最醒目的线索" not in value
        assert "记忆线索" not in value
        assert "如果还没有足够可靠的依据" not in value


def test_reply_sanitizer_drops_diagnostic_echo_that_cannot_be_cleaned_safely():
    raw = (
        "我又顺着刚才那股感觉往里摸了一点。"
        "现在最醒目的线索落在“在呀，银子。怎么啦？”附近。"
        "我也会把刚才被带起的记忆线索先贴在旁边。"
        "我想让它再自然长一小会儿，再决定是不是现在就开口。"
    )

    assert _clean_reply_text(raw) == ""


def test_prompt_hides_polluted_ap_tick_report_object_hints():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    polluted = "现在最醒目的线索落在在呀银子怎么啦附近，我也会把刚才被带起的记忆线索先贴在旁边"
    clean = "用户刚说在嘛"
    runtime.state["snapshots"] = [
        {
            "id": "polluted_tick",
            "tick_counter": 101,
            "created_at_ms": 1,
            "summary": {"total_er": 3.0, "total_ev": 0.1, "total_cp": 2.8, "mood_hint": "现实输入证据偏强"},
            "dominant_objects": [
                {"id": "st_bad", "type": "st", "display": polluted, "er": 99.0, "ev": 0.0, "cp": 99.0, "total_energy": 99.0},
                {"id": "agent_input", "type": "agent_input_text", "display": clean, "er": 6.0, "ev": 0.0, "cp": 4.0, "total_energy": 6.0},
            ],
            "top_objects": [],
            "object_cloud": [],
            "top_memory": [],
            "cognitive_feelings": [],
        }
    ]

    preview = runtime.prompt_preview({"text": "在嘛?", "write_snapshot": False})
    prompt_text = "\n".join(message["content"] for message in preview["messages"])

    assert "现在最醒目" not in prompt_text
    assert "被带起的记忆线索" not in prompt_text
    assert clean in prompt_text


def test_prompt_preview_hides_polluted_recent_thoughts():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config.persona_name = "测试人设"
    runtime.state["thoughts"].append(
        {
            "id": "thought_bad",
            "text": "我又往下想了一层，现在最醒目的线索落在旧回复附近。我也会把刚才被带起的记忆线索先贴在旁边。",
            "decision": "reply",
            "created_at_ms": 1,
            "llm_status": {"ok": True, "mode": "test"},
        }
    )

    preview = runtime.prompt_preview({"text": "在嘛?", "write_snapshot": False})
    prompt_text = "\n".join(message["content"] for message in preview["messages"])

    assert "当前人设名称：测试人设" in prompt_text
    assert "我又往下想了一层" not in prompt_text
    assert "最醒目的线索" not in prompt_text
    assert "记忆线索先贴在旁边" not in prompt_text


def test_agent_config_json_reader_accepts_utf8_bom(tmp_path):
    config_path = tmp_path / "agent_config.json"
    config_path.write_text(json.dumps({"persona_name": "小澪"}, ensure_ascii=False), encoding="utf-8-sig")

    loaded = _safe_read_json(config_path, {})

    assert loaded["persona_name"] == "小澪"


def test_napcat_wrapped_array_private_event_keeps_user_text_and_whitelist(tmp_path, monkeypatch):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow(
        [
            {
                "thought": "银子从 QQ 私聊发来下午好，我自然接住。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.86,
                "why": "normalization probe",
            }
        ],
        soft=1,
        hard=1,
    )
    runtime.config.qq_access_mode = "whitelist"
    runtime.config.qq_user_whitelist = ["200020002"]
    runtime.config.trigger_modes = ["private_all"]

    result = runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "_raw_payload": [
                {
                    "post_type": "message",
                    "message_type": "private",
                    "user_id": 200020002,
                    "message_id": -2147483648,
                    "sender": {"user_id": 200020002, "nickname": "银子"},
                    "raw_message": "下午好",
                    "message": [{"type": "text", "data": {"text": "下午好"}}],
                    "message_format": "array",
                }
            ],
        }
    )
    events = runtime.adapter_events(limit=20, view="detail")

    assert result["handled"] is True
    assert result["wake"]["access"]["reason"] == "user_whitelist"
    assert result["event"]["user_id"] == "200020002"
    assert result["event"]["conversation_id"] == "private:200020002"
    assert result["event"]["text"] == "下午好"
    received = [row for row in events["events"] if row.get("event") == "adapter_message_received"][-1]
    assert received["access_allowed"] is True
    assert received["access_reason"] == "user_whitelist"
    assert received["text"] == "下午好"
    assert received["event_payload"]["raw_event_preview"]["unwrapped_path"] == "_raw_payload > [0]"


def test_napcat_data_wrapped_private_event_normalizes_text_aliases():
    runtime = _runtime_for_flow([], soft=2, hard=3)

    normalized = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "data": {
                "post_type": "message",
                "message_type": "private",
                "sender": {"uin": "200020002", "nickname": "银子"},
                "messageId": "qq_private_2",
                "message_content": "11",
            },
        }
    )

    assert normalized["user_id"] == "200020002"
    assert normalized["message_id"] == "qq_private_2"
    assert normalized["conversation_id"] == "private:200020002"
    assert normalized["text"] == "11"
    assert normalized["raw_event_preview"]["unwrapped_path"] == "data"


def test_napcat_empty_segment_text_falls_back_to_raw_message():
    runtime = _runtime_for_flow([], soft=2, hard=3)

    normalized = runtime._normalize_adapter_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": 200020002,
            "raw_message": "11",
            "message": [],
        }
    )

    assert normalized["user_id"] == "200020002"
    assert normalized["text"] == "11"


def test_napcat_empty_private_event_is_filtered_before_wake_and_chat_append(tmp_path, monkeypatch):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config.qq_access_mode = "whitelist"
    runtime.config.qq_user_whitelist = ["200020002"]
    runtime.config.trigger_modes = ["private_all"]

    result = runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": 200020002,
            "message_id": "empty_1",
            "sender": {"user_id": 200020002, "nickname": "银子"},
            "raw_message": "",
            "message": [],
        }
    )
    events = runtime.adapter_events(limit=20, view="detail")["events"]

    assert result["handled"] is False
    assert result["wake"]["reason"] == "empty_message"
    assert result["wake"]["access"]["reason"] == "user_whitelist"
    assert runtime.state["messages"] == []
    assert any(row.get("event") == "adapter_message_received" and row.get("wake_reason") == "empty_message" for row in events)
    assert any(row.get("event") == "adapter_message_filtered" and row.get("wake_reason") == "empty_message" for row in events)
    assert not any(row.get("event") == "adapter_message_wake" for row in events)


def test_action_manager_active_reply_executor_records_system_feedback():
    manager = ActionManager(
        config_override={
            "enabled": True,
            "drive_decay_ratio": 1.0,
            "local_drive_modulation_by_rwd_pun_enabled": False,
            "action_fatigue_enabled": False,
            "executed_history_keep": 20,
        }
    )

    result = manager.run_action_cycle(
        trace_id="unit",
        tick_id="tick_active_reply",
        tick_index=1,
        innate_action_triggers=[
            {
                "action_id": "unit_active_reply",
                "action_kind": "active_reply",
                "gain": 1.2,
                "threshold": 0.8,
                "target_ref_object_id": "st_group_msg",
                "target_ref_object_type": "st",
                "target_display": "群聊里有人问 PA 要不要看一下",
                "params": {
                    "reason": "群聊内容明确邀请 PA 参与",
                    "role": "group_gate",
                    "conversation_id": "group:10001",
                    "target_label": "群聊 10001",
                    "reply_target": {"message_type": "group", "group_id": "10001", "conversation_id": "group:10001"},
                },
            }
        ],
    )

    executed = result["data"]["executed_actions"]
    assert executed
    row = executed[0]
    assert row["action_kind"] == "active_reply"
    assert row["success"] is True
    feedback = row["produced"]["system_feedback"]
    assert feedback["kind"] == "active_reply"
    assert feedback["conversation_id"] == "group:10001"
    assert manager.get_runtime_snapshot(trace_id="unit")["data"]["recent_executed_actions"][-1]["action_kind"] == "active_reply"


def test_group_all_ap_gate_should_wake_modes():
    runtime = _runtime_for_group_gate(execute_active_reply=False)

    ordinary = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("大家看看这个版本", message_id="g1")))
    at_hit = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("@PA 看看这个", message_id="g2")))
    keyword_hit = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("小PA 醒醒", message_id="g3")))
    private = runtime.should_wake(
        runtime._normalize_adapter_event(
            {
                "adapter": "napcat_qq",
                "post_type": "message",
                "message_type": "private",
                "user_id": "20002",
                "message": [{"type": "text", "data": {"text": "你好"}}],
            }
        )
    )

    assert ordinary["should_wake"] is False
    assert ordinary["ap_gate"] is True
    assert ordinary["gate_ticks"] == 3
    assert at_hit["should_wake"] is True
    assert at_hit["reason"] == "group_at"
    assert keyword_hit["should_wake"] is True
    assert keyword_hit["reason"] == "keyword"
    assert private["should_wake"] is True
    assert private["reason"] == "private_message"


def test_allow_group_without_at_uses_ap_gate_not_direct_llm_wake():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.allow_group_without_at = True
    runtime.config.trigger_modes = ["private_all", "group_at", "keyword"]

    result = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("普通群消息", group_id="928185505", message_id="allow_group_plain")))

    assert result["should_wake"] is False
    assert result["ap_gate"] is True
    assert result["reason"] == "group_allow_all_ap_gate"


def test_trigger_mode_legacy_group_gate_migrates_to_multi_modes():
    config = AgentConfig.from_dict({"trigger_mode": "group_all_ap_gate"})

    assert config.trigger_modes == ["private_all", "group_at", "keyword", "group_all_ap_gate"]
    assert config.trigger_mode == "private_all"


def test_llm_wait_tick_interval_can_be_zero_for_no_extra_wait():
    default_config = AgentConfig.from_dict({})
    zero_config = AgentConfig.from_dict({"llm_wait_tick_interval_ms": 0})
    negative_config = AgentConfig.from_dict({"llm_wait_tick_interval_ms": -20})

    assert default_config.llm_wait_tick_interval_ms == 0
    assert zero_config.llm_wait_tick_interval_ms == 0
    assert negative_config.llm_wait_tick_interval_ms == 0


def test_trigger_modes_support_independent_multi_select_semantics():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config = AgentConfig.from_dict(
        {
            "trigger_modes": ["private_all", "group_all_ap_gate"],
            "group_at_names": ["PA"],
            "wake_keywords": ["小PA"],
            "group_trigger_probability": 0,
        }
    )

    private = runtime.should_wake(runtime._normalize_adapter_event({"message_type": "private", "text": "你好"}))
    group_plain = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("大家看看这个版本", message_id="multi_plain")))
    group_at = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("@PA 看看这个", message_id="multi_at")))
    group_keyword = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("小PA 醒醒", message_id="multi_kw")))

    assert private["should_wake"] is True
    assert group_plain["should_wake"] is False
    assert group_plain["ap_gate"] is True
    assert group_at["should_wake"] is False
    assert group_at["ap_gate"] is True
    assert group_keyword["should_wake"] is False
    assert group_keyword["ap_gate"] is True


def test_trigger_modes_can_be_all_disabled_without_default_fallback():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config = AgentConfig.from_dict({"trigger_modes": [], "group_trigger_probability": 0})

    private = runtime.should_wake(runtime._normalize_adapter_event({"message_type": "private", "text": "小PA 醒醒"}))
    group = runtime.should_wake(runtime._normalize_adapter_event(_message_payload("@PA 小PA 醒醒", message_id="all_off")))

    assert runtime.config.trigger_modes == []
    assert private["should_wake"] is False
    assert group["should_wake"] is False
    assert not group.get("ap_gate")


def test_wake_policy_and_matrix_expose_multi_trigger_modes():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config = AgentConfig.from_dict(
        {
            "trigger_modes": ["keyword", "group_all_ap_gate"],
            "wake_keywords": ["小PA"],
            "group_trigger_probability": 0,
        }
    )

    policy = runtime.wake_policy()
    matrix = runtime.wake_matrix_probe({})

    assert policy["trigger_modes"] == ["keyword", "group_all_ap_gate"]
    assert "关键词唤醒" in policy["trigger_label"]
    assert "群聊全量（AP门控）" in policy["trigger_label"]
    assert matrix["trigger_modes"] == ["keyword", "group_all_ap_gate"]
    plain_case = next(row for row in matrix["cases"] if row["name"] == "群聊无触发")
    assert plain_case["should_wake"] is False
    assert plain_case["ap_gate"] is True
    assert plain_case["passed"] is True


def test_group_all_ap_gate_without_active_reply_never_calls_llm_and_keeps_ap_only():
    runtime = _runtime_for_group_gate(execute_active_reply=False)

    result = runtime.ingest_adapter_event(_message_payload("大家看看这个版本", message_id="g_plain"))

    assert result["handled"] is True
    assert result["mode"] == "group_all_ap_gate"
    assert result["ap_gate"]["triggered"] is False
    assert runtime.gateway.gate_calls == 0
    assert runtime.gateway.thought_calls == 0
    assert runtime.state["messages"] == []
    assert result["visible_message"] == {}
    assert len(runtime.app.reports) == 3


def test_group_all_ap_gate_plain_chatter_is_ap_only_without_continuity_or_llm():
    runtime = _runtime_for_group_gate(execute_active_reply=True)
    runtime.config.trigger_modes = ["group_all_ap_gate"]
    runtime.config.allow_group_without_at = True

    first = runtime.ingest_adapter_event(_message_payload("去哪儿呢", group_id="100010001", message_id="plain_where"))
    second = runtime.ingest_adapter_event(_message_payload("快母亲节了", group_id="100010001", message_id="plain_mothers_day"))

    assert first["handled"] is True
    assert first["mode"] == "group_all_ap_gate"
    assert first["ap_gate"]["triggered"] is False
    assert second["ap_gate"]["triggered"] is False
    assert runtime.state["messages"] == []
    assert runtime.state["group_continuity_windows"] == {}
    assert runtime.gateway.gate_calls == 0
    assert runtime.gateway.thought_calls == 0


def test_active_reply_gate_uses_configured_aliases_not_generic_bot_or_persona_name():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.active_reply_action_drive_gain = 1.0
    runtime.config.active_reply_action_threshold = 0.8
    runtime.config.group_at_names = ["小PA"]
    runtime.config.wake_keywords = ["醒醒"]
    runtime.config.persona_name = "澪"
    packet = {"summary": {}, "action": {"top_actions": []}}

    generic_bot = runtime._active_reply_gate_gain(
        packet=packet,
        normalized=runtime._normalize_adapter_event(_message_payload("今天我的bot差不多就好了", group_id="100020002", message_id="plain_bot_chatter")),
    )
    configured_alias = runtime._active_reply_gate_gain(
        packet=packet,
        normalized=runtime._normalize_adapter_event(_message_payload("小PA 看看这个", group_id="100020002", message_id="configured_alias")),
    )
    configured_keyword = runtime._active_reply_gate_gain(
        packet=packet,
        normalized=runtime._normalize_adapter_event(_message_payload("醒醒 看看这个", group_id="100020002", message_id="configured_keyword")),
    )
    persona_name_only = runtime._active_reply_gate_gain(
        packet=packet,
        normalized=runtime._normalize_adapter_event(_message_payload("澪 看看这个", group_id="100020002", message_id="persona_name_only")),
    )
    plain_where = runtime._active_reply_gate_gain(
        packet=packet,
        normalized=runtime._normalize_adapter_event(_message_payload("去哪儿呢", group_id="100020002", message_id="plain_where")),
    )

    assert generic_bot < 0.72
    assert configured_alias >= 0.72
    assert configured_keyword >= 0.72
    assert persona_name_only < 0.72
    assert plain_where == 0.0


def test_adapter_events_show_whitelist_filter_reason(tmp_path, monkeypatch):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config.qq_access_mode = "whitelist"
    runtime.config.qq_user_whitelist = ["999999"]
    runtime.config.qq_group_whitelist = []
    runtime.config.trigger_modes = ["private_all"]

    result = runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "20002",
            "sender": {"nickname": "银子"},
            "message": [{"type": "text", "data": {"text": "下午好"}}],
        }
    )
    events = runtime.adapter_events(limit=20, view="important")

    assert result["handled"] is False
    assert result["wake"]["reason"] == "not_in_whitelist"
    assert events["counts"]["filtered"] >= 1
    filtered = [row for row in events["events"] if row.get("event") == "adapter_message_filtered"]
    assert filtered
    assert filtered[-1]["access_allowed"] is False
    assert filtered[-1]["access_reason"] == "not_in_whitelist"
    assert filtered[-1]["text"] == "下午好"


def test_adapter_events_hide_stale_image_resolve_and_dry_run_noise(tmp_path, monkeypatch):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    rows = [
        {"event": "adapter_image_resolve_failed", "level": "warn", "ts": 1},
        {"event": "adapter_reply_dry_run", "level": "info", "outbound": True, "reply_text": "测试 dry-run", "ts": 2},
        {"event": "adapter_reply_failed", "level": "error", "reply_text": "真实失败", "ts": 3},
    ]
    adapter_log.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in rows) + "\n", encoding="utf-8")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.qq_napcat_dry_run = False

    important = runtime.adapter_events(limit=20, view="important")
    errors = runtime.adapter_events(limit=20, view="errors")
    detail = runtime.adapter_events(limit=20, view="detail")

    assert [row["event"] for row in important["events"]] == ["adapter_reply_failed"]
    assert [row["event"] for row in errors["events"]] == ["adapter_reply_failed"]
    assert [row["event"] for row in detail["events"]] == [row["event"] for row in rows]
    assert important["counts"]["warn"] == 0
    assert important["counts"]["replied"] == 1


def test_napcat_private_pass_enters_pa_chat_and_adapter_log(tmp_path, monkeypatch):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow(
        [
            {
                "thought": "银子从 QQ 私聊进来了，我先自然回应。",
                "decision": "reply",
                "reply_text": "下午好，银子。我在。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "private qq message",
            },
            {
                "thought": "已经回应过这条私聊了，先等他继续。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.86,
                "why": "settled",
            },
        ],
        soft=3,
        hard=5,
    )
    runtime.config.qq_napcat_enabled = False
    runtime.config.trigger_modes = ["private_all"]

    result = runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "20002",
            "sender": {"nickname": "银子"},
            "message_id": "qq_private_1",
            "message": [{"type": "text", "data": {"text": "下午好"}}],
        }
    )
    events = runtime.adapter_events(limit=30, view="detail")

    assert result["handled"] is True
    visible_messages = [row for row in runtime.state["messages"] if row.get("role") in {"user", "assistant"}]
    assert visible_messages[0]["text"] == "下午好"
    assert visible_messages[0]["source"] == "napcat_qq"
    assert visible_messages[0]["conversation_id"] == "private:20002"
    assert visible_messages[0]["adapter_label"]
    assert visible_messages[1]["text"] == "下午好，银子。我在。"
    assert visible_messages[1]["conversation_id"] == "private:20002"
    assert any(row.get("event") == "adapter_message_wake" for row in events["events"])
    assert any(row.get("event") == "adapter_message_replied" and row.get("reply_count") == 1 for row in events["events"])


def test_on_reply_dispatches_adapter_reply_before_post_ticks():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我先回一句，再继续让 AP 整理。",
                "decision": "reply",
                "reply_text": "我在。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "reply before post ticks",
            },
            {
                "thought": "已经发出去了，后续整理完成后可以停下。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.86,
                "why": "settled",
            },
        ],
        soft=3,
        hard=4,
    )
    runtime.config.post_thought_ticks = 2
    events = []

    def progress(update):
        events.append(("progress", update.get("stage"), len(runtime.app.reports)))

    def on_reply(reply):
        events.append(("reply", reply.get("text"), len(runtime.app.reports)))
        return {"ok": True, "message_id": "qq_1", "reply_id": reply.get("id")}

    result = runtime.send_message(
        {
            "text": "在嘛",
            "source": "napcat_qq",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002"},
            "_post_thought_ticks_override": 2,
        },
        progress=progress,
        on_reply=on_reply,
    )

    reply_index = next(index for index, item in enumerate(events) if item[0] == "reply")
    first_post_tick_index = next(index for index, item in enumerate(events) if item[0] == "progress" and item[1] == "post_thought_tick")
    assert reply_index < first_post_tick_index
    assert result["replies"][0]["adapter_dispatch"]["message_id"] == "qq_1"
    assert result["adapter_replies"][0]["message_id"] == "qq_1"


def test_adapter_reply_dispatch_log_is_marked_outbound_and_important(tmp_path, monkeypatch):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _fast_runtime_for_flow([], soft=2, hard=3)
    dispatch, outbound_rows, _ = runtime._make_adapter_reply_dispatcher(
        default_target={
            "adapter": "napcat_qq",
            "message_type": "private",
            "conversation_id": "private:200020002",
            "user_id": "200020002",
            "target_label": "私聊 银子 (200020002)",
        },
        adapter_event={
            "adapter": "napcat_qq",
            "message_type": "private",
            "conversation_id": "private:200020002",
            "user_id": "200020002",
            "target_label": "私聊 银子 (200020002)",
            "message_id": "qq_in_1",
        },
    )
    monkeypatch.setattr(
        runtime,
        "send_adapter_reply",
        lambda target, text, reply_id="", **kwargs: {"ok": True, "message_id": "qq_out_1", "reply_id": reply_id, "text": text, **kwargs},
    )

    dispatched = dispatch({"id": "reply_1", "text": "在呀。"})
    important_events = runtime.adapter_events(limit=20, view="important")["events"]
    dispatch_logs = [row for row in important_events if row.get("event") == "adapter_message_reply_dispatched"]

    assert dispatched["message_id"] == "qq_out_1"
    assert outbound_rows[0]["message_id"] == "qq_out_1"
    assert dispatch_logs
    assert dispatch_logs[-1]["outbound"] is True
    assert dispatch_logs[-1]["outbound_count"] == 1
    assert dispatch_logs[-1]["napcat_message_id"] == "qq_out_1"
    assert dispatch_logs[-1]["reply_text"] == "在呀。"


def test_group_all_ap_gate_active_reply_reject_writes_teacher_punish_without_reply_flow():
    runtime = _runtime_for_group_gate(
        execute_active_reply=True,
        gate_payload={"should_wake": False, "confidence": 0.96, "reason": "只是普通群聊闲聊，PA 不应插话"},
    )
    runtime.config.trigger_modes = ["group_all_ap_gate"]

    result = runtime.ingest_adapter_event(_message_payload("PA 你看看大家今晚吃什么这个话题要不要插话", message_id="g_reject"))

    assert result["handled"] is True
    assert result["ap_gate"]["triggered"] is True
    assert result["ap_gate"]["allowed"] is False
    assert runtime.gateway.gate_calls == 1
    assert runtime.gateway.thought_calls == 0
    assert runtime.state["messages"] == []
    assert result["ap_gate"]["teacher_gate"]["verdict"] == "reject"
    assert result["ap_gate"]["teacher_gate"]["punish"] > 0
    feedback = result["bridge_teacher_feedback"][0]
    assert feedback["kind"] == "active_reply"
    assert feedback["ok"] is False


def test_group_all_ap_gate_active_reply_allow_enters_reply_flow_without_duplicate_user_message():
    runtime = _runtime_for_group_gate(
        execute_active_reply=True,
        gate_payload={"should_wake": True, "confidence": 0.94, "reason": "群聊在直接请求 PA 帮忙"},
        thought_payloads=[
            {
                "thought": "群里在直接问我，我需要简短参与。",
                "decision": "reply",
                "reply_text": "我看到了，这里我建议先把问题拆成两步处理。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "group asked PA",
            },
            {
                "thought": "我已经回到群里了，先等他们继续。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.85,
                "why": "settled",
            },
        ],
    )

    result = runtime.ingest_adapter_event(_message_payload("帮忙看看这个问题应该怎么处理", message_id="g_allow"))

    assert result["handled"] is True
    flow = result["result"]
    assert flow["group_all_ap_gate"]["allowed"] is True
    assert runtime.gateway.gate_calls == 1
    assert runtime.gateway.thought_calls >= 2
    visible_users = [row for row in runtime.state["messages"] if row.get("role") == "user"]
    assert len(visible_users) == 1
    assert visible_users[0]["text"] == "帮忙看看这个问题应该怎么处理"
    assert len(flow["replies"]) == 1
    assert flow["replies"][0]["conversation_id"] == "group:10001"
    assert "建议先把问题拆成两步" in flow["replies"][0]["text"]
    assert flow["group_all_ap_gate"]["teacher_gate"]["reward"] > 0


def test_group_direct_wake_opens_continuity_window():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]

    result = runtime.ingest_adapter_event(_message_payload("@PA 在不在", message_id="cw_open"))

    assert result["handled"] is True
    window = runtime.state["group_continuity_windows"]["group:10001"]
    assert window["remaining"] == runtime.config.group_continuity_window_messages
    assert window["last_trigger_reason"] == "group_at"


def test_group_continuity_gate_pass_enters_main_reply_flow():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_continuity_window_messages = 3
    runtime.gateway = _TextGateThenThoughtGateway(
        gate_payload={"should_pass": True, "confidence": 0.91, "addressed_to_bot": True, "needs_reply": True, "reason": "在接着问 PA"},
        thought_payloads=[
            {
                "thought": "他在顺着刚才的群聊继续问我，我短一点接住。",
                "decision": "reply",
                "reply_text": "在的，你继续说。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "continuity gate passed",
            },
            {
                "thought": "这一句已经接住了，群里先别多刷。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.86,
                "why": "settled",
            },
        ],
    )
    runtime._activate_group_continuity_window(runtime._normalize_adapter_event(_message_payload("@PA 开个窗口", message_id="cw_seed")), reason="group_at")

    result = runtime.ingest_adapter_event(_message_payload("那你看看这个呢", message_id="cw_pass"))

    assert result["handled"] is True
    assert result["wake"]["reason"] == "group_continuity_gate_pass"
    assert runtime.gateway.text_calls
    assert result["result"]["replies"][0]["text"] == "在的，你继续说。"
    assert runtime.state["group_continuity_windows"]["group:10001"]["remaining"] == 3
    assert runtime.state["adapter_group_history"]["group:10001"][-1]["text"] == "那你看看这个呢"


def test_group_continuity_window_is_scoped_to_same_group_only():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime._activate_group_continuity_window(
        runtime._normalize_adapter_event(_message_payload("@PA 开个窗口", group_id="100010001", message_id="cw_seed_group_a")),
        reason="group_at",
    )

    same_group = runtime.should_wake(
        runtime._normalize_adapter_event(_message_payload("同群继续说", group_id="100010001", message_id="cw_same_group"))
    )
    other_group = runtime.should_wake(
        runtime._normalize_adapter_event(_message_payload("另一个群的普通消息", group_id="928185505", message_id="cw_other_group"))
    )

    assert same_group["continuity_gate"] is True
    assert same_group["group_continuity_window"]["conversation_id"] == "group:100010001"
    assert other_group["should_wake"] is False
    assert not other_group.get("continuity_gate")
    assert other_group["reason"] == "no_trigger"


def test_group_continuity_window_expires_after_idle_timeout():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_continuity_window_timeout_ms = 180000
    seed = runtime._normalize_adapter_event(_message_payload("@PA 开个窗口", group_id="100010001", message_id="cw_timeout_seed"))
    runtime._activate_group_continuity_window(seed, reason="group_at")
    runtime.state["group_continuity_windows"]["group:100010001"]["updated_at_ms"] = runtime.state["group_continuity_windows"]["group:100010001"]["updated_at_ms"] - 181000

    expired = runtime.should_wake(
        runtime._normalize_adapter_event(_message_payload("过了三分钟再说", group_id="100010001", message_id="cw_timeout_expired"))
    )

    assert expired["should_wake"] is False
    assert not expired.get("continuity_gate")
    assert expired["reason"] == "no_trigger"
    assert "group:100010001" not in runtime.state["group_continuity_windows"]


def test_group_continuity_window_timeout_zero_keeps_window_until_message_count():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_continuity_window_timeout_ms = 0
    seed = runtime._normalize_adapter_event(_message_payload("@PA 开个窗口", group_id="100010001", message_id="cw_no_timeout_seed"))
    runtime._activate_group_continuity_window(seed, reason="group_at")
    runtime.state["group_continuity_windows"]["group:100010001"]["updated_at_ms"] = runtime.state["group_continuity_windows"]["group:100010001"]["updated_at_ms"] - 24 * 60 * 60 * 1000

    active = runtime.should_wake(
        runtime._normalize_adapter_event(_message_payload("很久以后继续说", group_id="100010001", message_id="cw_no_timeout_active"))
    )
    runtime._trim_state()

    assert active["continuity_gate"] is True
    assert "group:100010001" in runtime.state["group_continuity_windows"]


def test_group_continuity_gate_uses_raw_group_history_not_only_visible_dialogue():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_continuity_gate_context_messages = 8
    runtime.gateway = _TextGateThenThoughtGateway(
        gate_payload={"should_pass": False, "confidence": 0.9, "addressed_to_bot": False, "needs_reply": False, "reason": "普通群聊"},
        thought_payloads=[],
    )
    seed = runtime._normalize_adapter_event(_message_payload("@PA 开个窗口", message_id="cw_hist_seed"))
    runtime._activate_group_continuity_window(seed, reason="group_at")

    runtime.ingest_adapter_event(_message_payload("第一条普通群消息", message_id="cw_hist_1"))
    runtime.ingest_adapter_event(_message_payload("第二条普通群消息", message_id="cw_hist_2"))

    gate_user_payload = json.loads(runtime.gateway.text_calls[-1]["messages"][1]["content"])
    raw_history_text = [row["text"] for row in gate_user_payload["recent_group_history"]]

    assert "第一条普通群消息" in raw_history_text
    assert "第二条普通群消息" in raw_history_text
    assert gate_user_payload["recent_visible_dialogue"] == []


def test_group_continuity_gate_payload_uses_configured_aliases_only():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_at_names = ["小PA"]
    runtime.config.wake_keywords = ["醒醒"]
    runtime.config.persona_name = "澪"
    runtime.config.group_continuity_gate_min_confidence = 0.9
    runtime.gateway = _TextGateThenThoughtGateway(
        gate_payload={"should_pass": False, "confidence": 0.91, "addressed_to_bot": False, "needs_reply": False, "reason": "普通群聊"},
        thought_payloads=[],
    )
    seed = runtime._normalize_adapter_event(_message_payload("@小PA 开个窗口", message_id="cw_alias_payload_seed"))
    runtime._activate_group_continuity_window(seed, reason="group_at")

    runtime.ingest_adapter_event(_message_payload("澪 看看这个", message_id="cw_alias_payload_message"))

    gate_user_payload = json.loads(runtime.gateway.text_calls[-1]["messages"][1]["content"])
    aliases = gate_user_payload["bot_aliases"]

    assert "小PA" in aliases
    assert "醒醒" in aliases
    assert "小醒醒" not in aliases
    assert "澪" not in aliases
    assert "bot" not in [str(item).lower() for item in aliases]


def test_group_continuity_gate_pass_leaves_bare_question_to_thought_layer():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_at_names = ["小PA"]
    runtime.config.wake_keywords = ["醒醒"]
    runtime.config.group_continuity_gate_min_confidence = 0.62
    runtime.gateway = _TextGateThenThoughtGateway(
        gate_payload={"should_pass": True, "confidence": 0.95, "addressed_to_bot": True, "needs_reply": True, "reason": "模型误判为需要回复"},
        thought_payloads=[
            {
                "thought": "这句像是群友之间的泛泛闲聊，不像是在对我说话。我先旁听，不插话刷屏。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.88,
                "why": "group message not directed to PA",
            }
        ],
    )
    seed = runtime._normalize_adapter_event(_message_payload("@小PA 开个窗口", group_id="100010001", message_id="cw_guard_seed"))
    runtime._activate_group_continuity_window(seed, reason="group_at")

    result = runtime.ingest_adapter_event(_message_payload("去哪儿呢", group_id="100010001", message_id="cw_guard_plain"))

    assert result["handled"] is True
    assert result["wake"]["reason"] == "group_continuity_gate_pass"
    assert result["wake"]["continuity_gate_result"]["raw_should_pass"] is True
    assert result["result"]["replies"] == []
    assert runtime.gateway.payloads == []
    assert runtime.state["messages"][0]["text"] == "去哪儿呢"


def test_group_continuity_gate_reject_consumes_window_and_closes():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.config.trigger_modes = ["group_at", "keyword"]
    runtime.config.group_continuity_window_messages = 2
    runtime.gateway = _TextGateThenThoughtGateway(
        gate_payload={"should_pass": False, "confidence": 0.88, "addressed_to_bot": False, "needs_reply": False, "reason": "群友彼此闲聊"},
        thought_payloads=[],
    )
    seed = runtime._normalize_adapter_event(_message_payload("@PA 开个窗口", message_id="cw_seed_reject"))
    runtime._activate_group_continuity_window(seed, reason="group_at")

    first = runtime.ingest_adapter_event(_message_payload("今晚吃啥", message_id="cw_reject_1"))
    second = runtime.ingest_adapter_event(_message_payload("我点外卖了", message_id="cw_reject_2"))

    assert first["handled"] is False
    assert first["group_continuity_window"]["remaining"] == 1
    assert second["handled"] is False
    assert "group:10001" not in runtime.state["group_continuity_windows"]


def test_prompt_explains_group_continuity_is_not_mandatory_reply():
    runtime = _runtime_for_group_gate(execute_active_reply=False)
    runtime.state["messages"].append(
        {
            "role": "user",
            "text": "那这个呢",
            "conversation_id": "group:10001",
            "adapter_label": "群聊 10001 / 银子 (20002)",
            "created_at_ms": 1,
        }
    )
    packet = runtime.build_prompt_packet(reports=[])
    messages = runtime._build_llm_messages(
        user_text="User 12:00:00 那这个呢",
        prompt_packet=packet,
        thought_index=0,
        thought_runtime={
            "adapter_context": {
                "active_conversation_id": "group:10001",
                "initial_reply_target": {"adapter": "napcat_qq", "message_type": "group", "group_id": "10001", "conversation_id": "group:10001"},
                "group_continuity_gate": {"should_pass": True, "confidence": 0.8, "reason": "窗口通过"},
            }
        },
    )
    prompt_text = "\n".join(str(item.get("content") or "") for item in messages)

    assert "群聊连续对话窗口" in prompt_text
    assert "不表示你必须回复" in prompt_text
    assert "不是对你说的" in prompt_text
    assert "角色人设也不该对此自然感兴趣" in prompt_text
    assert "去哪儿呢" in prompt_text
    assert "decision=sleep 或 silent" in prompt_text


class _ScriptedGateway:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.messages = []

    def generate(self, messages):
        self.messages.append(messages)
        if self.payloads:
            return self.payloads.pop(0), {"ok": True, "mode": "scripted"}
        return (
            {
                "thought": "我先安静下来。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "scripted fallback",
            },
            {"ok": True, "mode": "scripted"},
        )


class _FailOnceGateway:
    def __init__(self):
        self.messages = []
        self.calls = 0

    def generate(self, messages):
        self.calls += 1
        self.messages.append(messages)
        if self.calls == 1:
            return {}, {"ok": False, "mode": "scripted_error", "reason": "llm_call_failed", "error": "unit test api error"}
        return (
            {
                "thought": "我看到刚才调用失败了，所以先把这次状态收住。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "saw previous api error",
            },
            {"ok": True, "mode": "scripted"},
        )


class _WaitTickGateway:
    def __init__(self, delay=0.18):
        self.delay = delay
        self.calls = 0

    def generate(self, messages):
        import time

        self.calls += 1
        time.sleep(self.delay)
        if self.calls == 1:
            return (
                {
                    "thought": "我先回应一句。",
                    "decision": "reply",
                    "reply_text": "我在。",
                    "tool_calls": [],
                    "confidence": 0.9,
                    "why": "first",
                },
                {"ok": True, "mode": "wait_tick_probe"},
            )
        return (
            {
                "thought": "回复后可以先停下来。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "settled",
            },
            {"ok": True, "mode": "wait_tick_probe"},
        )


class _InterruptGateway:
    def __init__(self):
        self.messages = []
        self.calls = 0

    def generate(self, messages):
        import time

        self.calls += 1
        self.messages.append(messages)
        if self.calls == 1:
            time.sleep(0.16)
            return (
                {
                    "thought": "我先接住第一条输入。",
                    "decision": "reply",
                    "reply_text": "我听见了。",
                    "tool_calls": [],
                    "confidence": 0.9,
                    "why": "first",
                },
                {"ok": True, "mode": "interrupt_probe"},
            )
        return (
            {
                "thought": "新插入的问题已经进入了当前思考，我需要先回应新的外界输入。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "absorbed",
            },
            {"ok": True, "mode": "interrupt_probe"},
        )


class _PostReplyNoReviewGateway:
    def __init__(self, *, second_decision="sleep", second_reply=""):
        self.messages = []
        self.second_decision = second_decision
        self.second_reply = second_reply
        self.normal_calls = 0

    def generate(self, messages):
        self.messages.append(messages)
        content = messages[0]["content"] if messages else ""
        assert "同轮回复自检器" not in content
        self.normal_calls += 1
        if self.normal_calls == 1:
            return (
                {
                    "thought": "这句问候让我轻轻靠近一点。",
                    "decision": "reply",
                    "reply_text": "晚上好呀。今天过得怎么样？",
                    "tool_calls": [],
                    "confidence": 0.9,
                    "why": "first reply",
                },
                {"ok": True, "mode": "review_probe"},
            )
        if self.normal_calls == 2:
            return (
                {
                    "thought": "上一条回复已经把问候接住了，我可以先安静下来等用户继续说。",
                    "decision": self.second_decision,
                    "reply_text": self.second_reply,
                    "tool_calls": [],
                    "confidence": 0.86,
                    "why": "post reply settled by main prompt",
                },
                {"ok": True, "mode": "review_probe"},
            )
        return (
            {
                "thought": "修正已经说清楚了，我可以先停下来。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.86,
                "why": "settled",
            },
            {"ok": True, "mode": "review_probe"},
        )


class _WeatherThenReplyGateway:
    def __init__(self):
        self.messages = []
        self.normal_calls = 0

    def generate(self, messages):
        self.messages.append(messages)
        content = messages[0]["content"] if messages else ""
        assert "同轮回复自检器" not in content
        self.normal_calls += 1
        if self.normal_calls == 1:
            return (
                {
                    "thought": "我想先查清楚天气再回答。",
                    "decision": "tool_call",
                    "reply_text": "",
                    "tool_calls": [{"name": "weather", "args": {"location": "上海"}}],
                    "confidence": 0.9,
                    "why": "need current weather",
                },
                {"ok": True, "mode": "weather_probe"},
            )
        if self.normal_calls == 2:
            return (
                {
                    "thought": "天气结果已经回来了，我可以把它整理成一句清楚的话。",
                    "decision": "reply",
                    "reply_text": "上海今天晴朗，气温大约二十三度，适合出门走走。",
                    "tool_calls": [],
                    "confidence": 0.88,
                    "why": "tool result answered",
                },
                {"ok": True, "mode": "weather_probe"},
            )
        return (
            {
                "thought": "天气已经说清楚了，我先安静下来。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.82,
                "why": "settled after reply",
            },
            {"ok": True, "mode": "weather_probe"},
        )


class _GateThenThoughtGateway:
    def __init__(self, *, gate_payload: dict, thought_payloads: list[dict] | None = None):
        self.gate_payload = dict(gate_payload)
        self.thought_payloads = list(thought_payloads or [])
        self.messages = []
        self.gate_calls = 0
        self.thought_calls = 0

    def generate(self, messages):
        self.messages.append(messages)
        system = messages[0]["content"] if messages else ""
        if "教师门控" in system:
            self.gate_calls += 1
            return dict(self.gate_payload), {"ok": True, "mode": "gate_probe"}
        self.thought_calls += 1
        if self.thought_payloads:
            return self.thought_payloads.pop(0), {"ok": True, "mode": "thought_probe"}
        return (
            {
                "thought": "群聊里这次我已经参与过了，先安静下来。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "settled",
            },
            {"ok": True, "mode": "thought_probe"},
        )


class _TextGateThenThoughtGateway(_ScriptedGateway):
    def __init__(self, *, gate_payload: dict, thought_payloads: list[dict] | None = None):
        super().__init__(thought_payloads or [])
        self.gate_payload = dict(gate_payload)
        self.text_calls = []

    def generate_text(self, messages, model="", purpose="", max_tokens=None, response_format=None):
        self.text_calls.append({"messages": messages, "model": model, "purpose": purpose})
        return json.dumps(self.gate_payload, ensure_ascii=False), {"ok": True, "mode": "continuity_gate_probe", "model": model, "purpose": purpose}


class _FakeApp:
    def __init__(self):
        self._config = {}
        self._config_override = {}
        self.reports = []

    def run_cycle(self, text=None, labels=None):
        labels = dict(labels or {})
        tick = len(self.reports) + 1
        report = {
            "tick_id": f"tick_{tick}",
            "tick_counter": tick,
            "tick_labels": labels,
            "input_queue": {"tick_text": text or ""},
            "state_snapshot": {
                "summary": {"active_item_count": tick, "total_er": float(tick), "total_ev": 0.0, "total_cp": 0.0},
                "top_items": [],
            },
            "state_energy_summary": {
                "total_er": float(tick),
                "total_ev": 0.0,
                "total_cp": 0.0,
                "active_item_count": tick,
            },
            "emotion": {"channels": []},
            "action": {"top_actions": [], "executed": []},
            "hdb_snapshot": {},
            "timing": {},
        }
        self.reports.append(report)
        return report

    def get_dashboard_data(self):
        last = self.reports[-1] if self.reports else {}
        return {
            "tick_counter": len(self.reports),
            "state_snapshot": last.get("state_snapshot", {"summary": {}, "top_items": []}),
            "state_energy_summary": last.get("state_energy_summary", {"total_er": 0.0, "total_ev": 0.0, "total_cp": 0.0}),
            "hdb_snapshot": {},
            "last_report": last,
        }


class _ActiveReplyGateApp(_FakeApp):
    def __init__(self, *, execute_active_reply=True):
        super().__init__()
        self.execute_active_reply = bool(execute_active_reply)

    def run_cycle(self, text=None, labels=None):
        report = super().run_cycle(text=text, labels=labels)
        labels = dict(labels or {})
        executed = []
        if self.execute_active_reply:
            for trigger in labels.get("external_action_triggers") or []:
                if isinstance(trigger, dict) and trigger.get("action_kind") == "active_reply":
                    executed.append(
                        {
                            "action_id": trigger.get("action_id"),
                            "action_kind": "active_reply",
                            "success": True,
                            "target_display": trigger.get("target_display") or "",
                            "target_ref_object_id": trigger.get("target_ref_object_id") or "",
                            "target_ref_object_type": trigger.get("target_ref_object_type") or "",
                            "params": trigger.get("params") or {},
                            "produced": {
                                "system_feedback": {
                                    "kind": "active_reply",
                                    "reason": (trigger.get("params") or {}).get("reason", ""),
                                    "role": (trigger.get("params") or {}).get("role", ""),
                                    "conversation_id": (trigger.get("params") or {}).get("conversation_id", ""),
                                    "target_label": (trigger.get("params") or {}).get("target_label", ""),
                                    "reply_target": (trigger.get("params") or {}).get("reply_target", {}),
                                }
                            },
                        }
                    )
        report["action"] = {"top_actions": [], "executed_actions": executed, "executed": executed}
        return report


def _runtime_for_flow(payloads, *, soft=2, hard=8, resets=2):
    runtime = AgentRuntime(_FakeApp())
    runtime.save = lambda: None
    runtime.record_event = lambda payload: None
    runtime._reload_config_before_adapter_send = False
    runtime.state = {
        "session_id": "test",
        "messages": [],
        "thoughts": [],
        "turns": [],
        "snapshots": [],
        "outbound": {"last_send_at_ms": 0},
        "group_continuity_windows": {},
        "adapter_group_history": {},
        "background_agency": {},
        "created_at_ms": 0,
        "updated_at_ms": 0,
    }
    runtime.config = AgentConfig(
        llm_enabled=True,
        api_key="test",
        model="test-model",
        pre_thought_ticks=0,
        post_thought_ticks=0,
        max_thoughts_per_turn=soft,
        max_total_thought_steps_per_turn=hard,
        thought_budget_reset_limit=resets,
        auto_reply=True,
    )
    runtime.gateway = _ScriptedGateway(payloads)
    return runtime


def test_snapshot_metrics_are_compacted_for_fast_saves():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.config.snapshot_metric_top_text_chars = 90
    runtime.config.snapshot_metric_top_rows = 2
    metrics = {
        "pool_total_er": 12.3,
        "pool_er_top5_text": "很长的对象文本" * 80,
        "pool_er_top5": [
            {"item_id": "spi_1", "ref_object_id": "st_1", "ref_object_type": "st", "display": "对象一", "er": 1.0},
            {"item_id": "spi_2", "ref_object_id": "st_2", "ref_object_type": "st", "display": "对象二", "er": 0.5},
            {"item_id": "spi_3", "ref_object_id": "st_3", "ref_object_type": "st", "display": "对象三", "er": 0.2},
        ],
        "huge_debug_blob": [{"x": index, "payload": "x" * 200} for index in range(50)],
    }

    compact = runtime._compact_snapshot_metrics(metrics)

    assert compact["pool_total_er"] == 12.3
    assert len(compact["pool_er_top5_text"]) <= 90
    assert len(compact["pool_er_top5"]) == 2
    assert "huge_debug_blob" not in compact


def test_snapshot_history_returns_compact_rows_without_raw_refs():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.state["snapshots"] = [
        {
            "id": "tick_1",
            "kind": "ap_tick",
            "created_at_ms": 1,
            "tick_counter": 1,
            "summary": {"total_er": 1.0, "total_ev": 0.0, "total_cp": 2.0},
            "dominant_objects": [
                {
                    "rank": 1,
                    "id": "pa_st_1",
                    "type": "st",
                    "display": "对象",
                    "full_display": "对象完整内容",
                    "er": 1.0,
                    "ev": 0.0,
                    "cp": 2.0,
                    "raw_ref": {"item_id": "spi_should_not_leak"},
                }
            ],
            "top_objects": [],
            "object_cloud": [],
            "metrics": {"pool_total_er": 1.0, "timing_total_logic_ms": 12.0},
        }
    ]

    page = runtime.history(kind="snapshots", limit=10, offset=0)

    assert page["total"] == 1
    item = page["items"][0]
    assert item["top_objects"][0]["display"] == "对象"
    assert "raw_ref" not in item["top_objects"][0]
    assert item["metrics"]["timing_total_logic_ms"] == 12.0


def test_compact_status_cached_reuses_cached_payload(monkeypatch):
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime._last_status_compact = {"cached": True}
    runtime._last_compact_packet = {"summary": {}}
    monkeypatch.setattr(runtime, "_maybe_reload_config_from_disk", lambda: False)

    def fail_rebuild(*args, **kwargs):
        raise AssertionError("compact status cache should not rebuild when config/state did not change")

    monkeypatch.setattr(runtime, "_build_compact_status_payload", fail_rebuild)

    assert runtime.status_compact_cached() == {"cached": True}


def test_attention_action_feedback_is_deferred_without_extra_ap_cycle():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.app.reports = []
    report = {
        "tick_id": "tick_attention",
        "tick_counter": 1,
        "tick_labels": {"source": "agent_pre_llm_tick"},
        "state_snapshot": {
            "summary": {"active_item_count": 4, "total_er": 1.0, "total_ev": 0.0, "total_cp": 3.0},
            "top_items": [{"item_id": "spi_1", "ref_object_id": "st_1", "ref_object_type": "st", "display": "重要目标", "er": 1.0}],
        },
        "state_energy_summary": {"total_er": 1.0, "total_ev": 0.0, "total_cp": 3.0, "active_item_count": 4},
        "action": {
            "executed_actions": [
                {
                    "action_kind": "attention_focus",
                    "success": True,
                    "target_display": "重要目标",
                    "produced": {"system_feedback": {"text": "重要目标"}},
                }
            ]
        },
        "timing": {},
    }

    bridged = runtime._bridge_tick_side_effects(report, source="agent_pre_llm_tick", allow_internal_think=False)

    assert runtime.app.reports == []
    assert bridged["bridge_reports"] == []
    assert bridged["teacher_feedback"][0]["deferred"] is True
    assert bridged["timing"]["deferred_feedback_count"] == 1
    assert runtime._pending_teacher_feedback_labels

    next_report = runtime._run_app_cycle(text=None, labels={"source": "unit_next_tick"})

    assert next_report["tick_labels"]["pending_teacher_feedback_count"] == 1
    assert next_report["tick_labels"]["teacher"]["teacher_rwd"] > 0
    assert runtime._pending_teacher_feedback_labels == []


class _FastCycleRuntime(AgentRuntime):
    def _run_app_cycle(self, *, text=None, labels=None):
        import time

        started = time.perf_counter()
        labels = dict(labels or {})
        tick = len(getattr(self, "_cycle_reports", [])) + 1
        report = {
            "tick_id": f"tick_{tick}",
            "tick_labels": labels,
            "input_queue": {"tick_text": text or ""},
            "state_snapshot": {"summary": {"active_item_count": tick}, "top_items": []},
            "state_energy_summary": {"total_er": float(tick), "total_ev": 0.0, "total_cp": 0.0, "active_item_count": tick},
            "emotion": {"channels": []},
            "action": {"top_actions": [], "executed": []},
            "hdb_snapshot": {},
            "timing": {},
        }
        if not hasattr(self, "_cycle_reports"):
            self._cycle_reports = []
        self._cycle_reports.append(report)
        self._last_cycle_elapsed_ms = (time.perf_counter() - started) * 1000.0
        return report


def _fast_runtime_for_flow(payloads, *, soft=2, hard=8, resets=2):
    runtime = _FastCycleRuntime(_FakeApp())
    runtime.save = lambda: None
    runtime.record_event = lambda payload: None
    runtime.state = {
        "session_id": "test",
        "messages": [],
        "thoughts": [],
        "turns": [],
        "snapshots": [],
        "outbound": {"last_send_at_ms": 0},
        "group_continuity_windows": {},
        "adapter_group_history": {},
        "background_agency": {},
        "created_at_ms": 0,
        "updated_at_ms": 0,
    }
    runtime.config = AgentConfig(
        llm_enabled=True,
        api_key="test",
        model="test-model",
        pre_thought_ticks=0,
        post_thought_ticks=0,
        max_thoughts_per_turn=soft,
        max_total_thought_steps_per_turn=hard,
        thought_budget_reset_limit=resets,
        auto_reply=True,
    )
    runtime.gateway = _ScriptedGateway(payloads)
    return runtime


def _runtime_for_group_gate(*, execute_active_reply=True, gate_payload=None, thought_payloads=None):
    runtime = AgentRuntime(_ActiveReplyGateApp(execute_active_reply=execute_active_reply))
    runtime.save = lambda: None
    runtime.record_event = lambda payload: None
    runtime.state = {
        "session_id": "test",
        "messages": [],
        "thoughts": [],
        "turns": [],
        "snapshots": [],
        "outbound": {"last_send_at_ms": 0},
        "group_continuity_windows": {},
        "adapter_group_history": {},
        "background_agency": {},
        "created_at_ms": 0,
        "updated_at_ms": 0,
    }
    runtime.config = AgentConfig(
        llm_enabled=True,
        api_key="test",
        model="test-model",
        pre_thought_ticks=0,
        post_thought_ticks=0,
        max_thoughts_per_turn=3,
        max_total_thought_steps_per_turn=4,
        thought_budget_reset_limit=1,
        auto_reply=True,
        trigger_mode="group_all_ap_gate",
        group_all_ap_gate_ticks=3,
        active_reply_action_drive_gain=2.0,
        active_reply_action_threshold=0.8,
        group_trigger_probability=0,
        qq_napcat_enabled=False,
    )
    runtime.gateway = _GateThenThoughtGateway(
        gate_payload=gate_payload or {"should_wake": False, "confidence": 0.95, "reason": "普通群聊暂不插话"},
        thought_payloads=thought_payloads or [],
    )
    return runtime


def _report_source(report):
    if not isinstance(report, dict):
        return ""
    if report.get("source"):
        return report.get("source")
    labels = report.get("tick_labels")
    return labels.get("source") if isinstance(labels, dict) else ""


def _current_timeline_from_prompt(prompt: str) -> str:
    marker = "当前同轮事件时间线和 LLM 输入上下文："
    if marker not in prompt:
        return prompt
    tail = prompt.split(marker, 1)[1]
    return tail.split("这是硬计数", 1)[0]


def test_reply_does_not_end_turn_until_followup_decision():
    runtime = _runtime_for_flow(
        [
            {
                "thought": "我先回应他一句，但心里还在继续听。",
                "decision": "reply",
                "reply_text": "我在。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "visible reply",
            },
            {
                "thought": "这句话已经落下来了，我可以先安静。",
                "decision": "silent",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "settled",
            },
        ],
        soft=3,
        hard=6,
    )

    result = runtime.send_message({"text": "你好"})

    assert len(result["replies"]) == 1
    assert len(result["thoughts"]) == 2
    assert result["turn"]["decision"] == "silent"


def test_continue_thinking_resets_soft_budget_window():
    runtime = _runtime_for_flow(
        [
            {
                "thought": "我还没有把这件事想完。",
                "decision": "continue_thinking",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "need more",
            },
            {
                "thought": "重置以后线索清楚了一点。",
                "decision": "reply",
                "reply_text": "我想清楚一点了。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "reply after reset",
            },
            {
                "thought": "回复之后我不急着再推进。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "idle",
            },
        ],
        soft=1,
        hard=6,
        resets=2,
    )

    result = runtime.send_message({"text": "继续想一下"})

    assert len(result["thoughts"]) >= 3
    assert result["turn"]["thought_runtime"]["reset_count"] >= 1
    assert result["turn"]["thought_runtime"]["reset_limit"] == 2


def test_second_prompt_uses_timeline_without_extra_llm_self_review():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    runtime.gateway = _PostReplyNoReviewGateway(second_decision="sleep", second_reply="")

    result = runtime.send_message({"text": "晚上好"})

    assert len(result["replies"]) == 1
    assert result["turn"]["decision"] == "sleep"
    assert runtime.gateway.normal_calls == 2
    assert len(runtime.gateway.messages) == 2
    assert all("同轮回复自检器" not in call[0]["content"] for call in runtime.gateway.messages)
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "同轮事件时间线" in second_prompt
    assert "当前对话框内容信息" in second_prompt
    assert "发送者: PA" in second_prompt
    assert "当前对话中最新消息" in second_prompt
    assert "最新可见消息来自 PA，用户在此之后没有再次输入新消息" in second_prompt
    assert "PA 回复是你已经真实说出口的话" in second_prompt
    assert "可见回复已发送成功" in second_prompt
    assert "回复连续性账本" in second_prompt
    assert "本轮已经发送过可见回复" in second_prompt
    assert "默认应 sleep 或 silent" in second_prompt
    assert "reply_text 写作任务卡" in second_prompt
    assert "上一条 reply 的连续性锚点" in second_prompt
    assert "正例 1" in runtime.gateway.messages[1][0]["content"]
    assert "内心想法演进协议" in runtime.gateway.messages[1][0]["content"]
    assert "回复文本写作协议" in runtime.gateway.messages[1][0]["content"]
    assert "用户问“你有真正的内心吗？现在有什么感觉？”" in runtime.gateway.messages[1][0]["content"]
    assert "正例 8" in runtime.gateway.messages[1][0]["content"]
    assert "一般对用户的一条普通消息，一条高质量 reply 就够" in runtime.gateway.messages[1][0]["content"]
    assert "没有新输入/工具结果" in runtime.gateway.messages[1][0]["content"]


def test_second_corrective_reply_can_survive_without_extra_self_review():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    runtime.gateway = _PostReplyNoReviewGateway(second_decision="reply", second_reply="我刚才问得有点泛，我想更准确地说：如果你愿意，可以只告诉我今晚最明显的一种感受。")

    result = runtime.send_message({"text": "晚上好"})

    assert len(result["replies"]) == 2
    assert result["turn"]["decision"] == "sleep"
    assert runtime.gateway.normal_calls == 3
    assert all("同轮回复自检器" not in call[0]["content"] for call in runtime.gateway.messages)
    assert "如果你愿意" in result["replies"][1]["text"]


def test_tool_call_first_turn_then_reply_uses_timeline_without_self_review():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    runtime.gateway = _WeatherThenReplyGateway()
    runtime.tools.run = lambda name, args, source="": {
        "tool": name,
        "ok": True,
        "output": {"summary": "上海今天晴朗，约 23°C", "location": args.get("location")},
        "summary": "上海今天晴朗，约 23°C",
    }

    result = runtime.send_message({"text": "上海天气怎么样"})

    assert len(result["replies"]) == 1
    assert "上海今天晴朗" in result["replies"][0]["text"]
    assert len(runtime.gateway.messages) >= 2
    assert runtime.gateway.normal_calls >= 2
    assert all("同轮回复自检器" not in call[0]["content"] for call in runtime.gateway.messages[:2])
    second_prompt = runtime.gateway.messages[1][1]["content"]
    second_timeline = _current_timeline_from_prompt(second_prompt)
    second_timeline_events = "\n".join(line for line in second_timeline.splitlines() if re.match(r"^\d+\. ", line.strip()))
    assert "同轮事件时间线" in second_prompt
    assert "决定调用工具" in second_timeline
    assert "工具结果已返回" in second_timeline
    assert "可见回复已发送成功" not in second_timeline_events


def test_agent_prompt_packet_uses_light_dashboard_path():
    runtime = _fast_runtime_for_flow([], soft=2, hard=3)

    def fail_full_dashboard():
        raise AssertionError("full dashboard path should not be used for agent prompt packet")

    runtime.app.get_dashboard_data = fail_full_dashboard

    packet = runtime.build_prompt_packet(reports=[])

    assert "summary" in packet
    assert "module_configs" not in packet
    assert "recent_cycles" not in packet


def test_agent_prompt_packet_from_report_skips_live_dashboard_probe():
    runtime = _fast_runtime_for_flow([], soft=2, hard=3)
    report = runtime._run_app_cycle(text="你好", labels={"source": "unit_report_packet"})

    def fail_state_snapshot(*args, **kwargs):
        raise AssertionError("live state snapshot should not be used when a fresh report is available")

    runtime.app.pool = type("PoolProbe", (), {"get_state_snapshot": fail_state_snapshot})()
    runtime.app.hdb = type("HdbProbe", (), {"get_hdb_snapshot": fail_state_snapshot})()

    packet = runtime.build_prompt_packet(reports=[report])

    assert packet["_source_report"] is report
    assert packet["tick_counter"] == int(str(report["tick_id"]).split("_")[-1])
    assert packet["summary"]["total_er"] == report["state_energy_summary"]["total_er"]


def test_prompt_packet_projects_input_text_when_state_top_items_are_empty():
    runtime = _fast_runtime_for_flow([], soft=2, hard=3)
    report = runtime._run_app_cycle(text="input cloud probe", labels={"source": "unit_input_projection"})

    packet = runtime.build_prompt_packet(reports=[report])
    cloud_text = " ".join(str(item.get("display") or "") for item in packet.get("object_cloud", []))
    dominant_text = " ".join(str(item.get("display") or "") for item in packet.get("dominant_objects", []))

    assert packet["summary"]["total_er"] > 0
    assert "input cloud probe" in cloud_text
    assert "input cloud probe" in dominant_text
    assert any(item.get("type") == "agent_input_text" for item in packet.get("object_cloud", []))


def test_wait_tick_progress_keeps_original_input_visible_during_empty_ticks():
    runtime = _fast_runtime_for_flow([], soft=3, hard=3)
    runtime.config.pre_thought_ticks = 1
    runtime.config.post_thought_ticks = 0
    runtime.config.run_ap_while_waiting_llm = True
    runtime.config.llm_wait_tick_interval_ms = 50
    runtime.config.llm_wait_tick_max_per_call = 4
    runtime.gateway = _WaitTickGateway(delay=0.28)
    progress_rows = []

    runtime.send_message(
        {"text": "input cloud probe", "_run_ap_while_waiting_llm": True, "_pre_thought_ticks_override": 1},
        progress=lambda update: progress_rows.append(dict(update or {})),
    )

    wait_rows = [row for row in progress_rows if row.get("stage") == "waiting_llm_ap_tick"]
    assert wait_rows
    for row in wait_rows:
        cloud_text = " ".join(str(item.get("display") or "") for item in row.get("ap_packet", {}).get("object_cloud", []))
        assert "input cloud probe" in cloud_text


def test_prompt_exposes_prior_thoughts_and_replies_for_evolution():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "第一条想法。",
                "decision": "reply",
                "reply_text": "第一条回复。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "first",
            },
            {
                "thought": "第二条想法明显收束。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "settled",
            },
        ],
        soft=4,
        hard=6,
    )

    runtime.send_message({"text": "测试"})

    assert len(runtime.gateway.messages) >= 2
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "prior_thoughts_this_turn" in second_prompt
    assert "第一条想法" in second_prompt
    assert "prior_replies_this_turn" in second_prompt
    assert "第一条回复" in second_prompt


def test_second_reply_is_not_hard_blocked_but_feedback_enters_next_prompt():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "用户想听自我介绍，我先自然地说清楚。",
                "decision": "reply",
                "reply_text": "你好呀，我是澪，一个喜欢静静倾听，也会在你需要时陪你的伙伴。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "self intro",
            },
            {
                "thought": "我想把自我介绍说得更细一点。",
                "decision": "reply",
                "reply_text": "你好呀，我是澪，一个喜欢静静倾听，也会在你需要时陪你的伙伴。",
                "tool_calls": [],
                "confidence": 0.82,
                "why": "repeat self intro",
            },
            {
                "thought": "刚才的回复动作已经提醒我这是重复发送，我先收束下来等用户继续问。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.86,
                "why": "reply action rejected duplicate",
            },
        ],
        soft=5,
        hard=6,
    )

    result = runtime.send_message({"text": "晚好,自我介绍一下?"})

    assert len(result["replies"]) == 2
    assert len(runtime.gateway.messages) >= 3
    third_prompt = runtime.gateway.messages[2][1]["content"]
    assert "reply_action" in third_prompt
    assert "不硬拦截" in third_prompt or "硬拦截" in third_prompt
    assert "prior_replies_this_turn" in third_prompt
    assert "你好呀，我是澪" in third_prompt


def test_prompt_stage_order_runs_pre_ticks_before_building_ap_packet():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我已经处理完了，先安静下来。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "latency stage probe",
            }
        ],
        soft=1,
        hard=1,
    )
    runtime.config.pre_thought_ticks = 3
    progress_rows = []

    runtime.send_message({"text": "晚上好"}, progress=lambda update: progress_rows.append(dict(update or {})))

    stages = [row.get("stage") for row in progress_rows]
    assert "building_ap_packet" in stages
    assert stages.index("pre_llm_tick") < stages.index("building_ap_packet")
    assert len([row for row in progress_rows if row.get("stage") == "pre_llm_tick_done"]) == 3


def test_fast_runtime_reaches_llm_prompt_after_five_pre_ticks_under_budget():
    import time

    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我已经看见输入，先收束。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "latency budget probe",
            }
        ],
        soft=1,
        hard=1,
    )
    runtime.config.pre_thought_ticks = 5
    waiting_at = {"elapsed": None}
    start = time.perf_counter()

    def progress(update):
        if update.get("stage") == "waiting_llm" and waiting_at["elapsed"] is None:
            waiting_at["elapsed"] = time.perf_counter() - start

    runtime.send_message({"text": "晚上好"}, progress=progress)

    assert waiting_at["elapsed"] is not None
    assert waiting_at["elapsed"] < 1.0
    assert len(getattr(runtime, "_cycle_reports", [])) >= 6


def test_prompt_preview_reports_section_budgets():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)

    preview = runtime.prompt_preview({"text": "看一下当前提示词预算"})
    budgets = preview["budgets"]
    section_rows = budgets["section_rows"]

    assert budgets["prompt_chars"] > 0
    assert section_rows
    assert any(row["label"] == "user:当前同轮事件时间线和 LLM 输入上下文" for row in section_rows)
    assert any(row["label"] == "user:回复连续性账本" for row in section_rows)
    assert any(row["label"] == "user:AP 内在状态包（LLM compact）" for row in section_rows)
    assert budgets["system_estimated_tokens"] > 0
    assert budgets["user_estimated_tokens"] > 0
    assert budgets["estimated_tokens"] >= budgets["system_estimated_tokens"]


def test_prompt_preview_can_write_full_prompt_snapshot(tmp_path, monkeypatch):
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    snapshot_path = tmp_path / "agent_last_prompt_snapshot.json"
    monkeypatch.setattr("observatory.agent_runtime._prompt_snapshot_path", lambda: snapshot_path)

    preview = runtime.prompt_preview({"text": "写出完整 prompt 样本", "write_snapshot": True})

    assert preview["files"]["prompt_snapshot"]["exists"] is True
    payload = __import__("json").loads(snapshot_path.read_text(encoding="utf-8"))
    assert payload["messages"][0]["role"] == "system"
    assert "回复连续性和拟人节制" in payload["messages"][0]["content"]
    assert "内心想法演进协议" in payload["messages"][0]["content"]
    assert "回复文本写作协议" in payload["messages"][0]["content"]
    assert "回复连续性账本" in payload["messages"][1]["content"]
    assert "已回复后无新功能的反面示例" in payload["messages"][1]["content"]
    assert payload["budgets"]["estimated_tokens"] > 0


def test_prompt_treats_ap_metrics_as_self_state_not_external_labels():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)

    preview = runtime.prompt_preview({"text": "我看到你好像有失调感、惊异感、多巴胺也比较高，这些不会带给你感觉吗？"})
    system_text = preview["messages"][0]["content"]

    assert "AP 是你的认知核心、情绪核心、注意核心和身体化状态近似" in system_text
    assert "LLM 只是把 AP 的当前状态" in system_text
    assert "这些 AP 指标就是我的内在状态通道" in system_text
    assert "不要用“严格来说，我没有人类意义上的灵魂或身体感受”作为主回答开头" in system_text
    assert "回答必须贴合这些指标" in system_text
    assert "反例：回答“我不会感受到多巴胺，它只是系统标签”" in system_text
    assert "这些只是系统倾向" in system_text
    assert "PA/当前人格此刻自己的状态" in preview["messages"][1]["content"]


def test_system_prompt_has_no_hardcoded_persona_identity():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    runtime.config.persona_name = "测试人格"
    runtime.config.persona_text = "只用这个测试人格说话。"

    preview = runtime.prompt_preview({"text": "检查人设残留"})
    system_text = preview["messages"][0]["content"]
    user_text = preview["messages"][1]["content"]

    assert "中文名澪" not in system_text
    assert "PA/澪" not in system_text
    assert "我是澪" not in system_text
    assert "当前人设名称：测试人格" in user_text
    assert "只用这个测试人格说话。" in user_text


def test_prompt_exposes_full_realtime_nt_and_cfs_without_generic_metric_hallucination():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    report = runtime._run_app_cycle(text="我在吃凉面", labels={"source": "unit"})
    report["cognitive_feeling"] = {
        "signals": [
            {"kind": "surprise", "strength": 0.22},
            {"kind": "expectation", "strength": 0.17},
            {"kind": "expectation_unverified", "strength": 0.10},
            {"kind": "pressure", "strength": 0.05},
            {"kind": "relief", "strength": 0.04},
        ]
    }
    report["emotion"] = {
        "nt_state_after": {
            "DA": 0.62,
            "SER": 0.53,
            "FOC": 0.52,
            "NOV": 0.47,
            "OXY": 0.43,
            "COR": 0.38,
            "ADR": 0.36,
            "END": 0.34,
        }
    }
    runtime._cycle_reports[-1] = report

    packet = runtime.build_prompt_packet(reports=[report])
    messages = runtime._build_llm_messages(
        user_text="除了我说的那些实时状态指标，你还能看到哪些？",
        prompt_packet=packet,
        thought_index=0,
    )
    llm_packet = runtime._compact_prompt_packet_for_llm(packet)
    system_text = messages[0]["content"]
    user_text = messages[1]["content"]

    assert "cognitive_feelings_all" in user_text
    assert "nt_channels_all" in user_text
    assert "不要补充未出现的通用心理学指标" in user_text
    assert "情绪价度、唤醒度、情绪粒度、预测误差、工作记忆占用率" in system_text
    assert "这是错误，因为这些没有出现在 AP 实时状态包里" in system_text
    assert [row["label_zh"] for row in llm_packet["cognitive_feelings_all"][:4]] == [
        "惊异感",
        "期待感",
        "未确认预期",
        "压迫感",
    ]
    assert {row["channel"]: row["value"] for row in llm_packet["nt_channels_all"]}["DA"] == 0.62
    assert {row["channel"]: row["label_zh"] for row in llm_packet["nt_channels_all"]}["SER"] == "安定"


def test_same_turn_tool_result_is_in_next_llm_prompt():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我需要先查一下真实天气。",
                "decision": "tool_call",
                "reply_text": "",
                "tool_calls": [{"name": "weather", "args": {"location": "上海"}}],
                "confidence": 0.9,
                "why": "need weather",
            },
            {
                "thought": "工具结果已经回来，我可以吸收后再回答。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "absorbed tool",
            },
        ],
        soft=4,
        hard=6,
    )
    runtime.tools.run = lambda name, args, source="": {
        "tool": name,
        "ok": False,
        "output": {"error": "HTTP Error 502: Bad Gateway", "location": args.get("location")},
        "summary": "天气工具这次没有成功返回 上海 的结果，我需要稍后重试或换一种查询方式。",
    }

    runtime.send_message({"text": "上海天气怎么样"})

    assert len(runtime.gateway.messages) >= 2
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "刚刚的工具结果如下" in second_prompt
    assert "weather:失败" in second_prompt
    assert "上海" in second_prompt
    assert "HTTP Error" in second_prompt or "没有成功返回 上海" in second_prompt


def test_same_turn_llm_error_status_is_in_next_llm_prompt():
    runtime = _fast_runtime_for_flow([], soft=4, hard=6)
    runtime.gateway = _FailOnceGateway()

    runtime.send_message({"text": "测试 API 报错上下文"})

    assert len(runtime.gateway.messages) >= 2
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "prior_thoughts_this_turn" in second_prompt
    assert "llm_call_failed" in second_prompt
    assert "unit test api error" in second_prompt


def test_adapter_prompt_uses_active_conversation_and_target():
    runtime = _runtime_for_flow(
        [
            {
                "thought": "我先接住这个私聊问题。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "prompt probe",
            }
        ],
        soft=1,
        hard=1,
    )
    runtime.state["messages"] = [
        {"role": "user", "text": "群里的旧话", "conversation_id": "group:10001", "adapter_label": "群聊 10001", "created_at_ms": 1},
        {"role": "user", "text": "私聊里的旧话", "conversation_id": "private:20002", "adapter_label": "私聊 银子", "created_at_ms": 2},
    ]

    runtime.send_message(
        {
            "text": "私聊新问题",
            "source": "napcat_qq",
            "conversation_id": "private:20002",
            "adapter_label": "私聊 银子",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "20002", "conversation_id": "private:20002", "target_label": "私聊 银子"},
        }
    )
    prompt_text = "\n".join(message["content"] for message in runtime.gateway.messages[-1])

    assert "平台适配器会话与回复目标" in prompt_text
    assert "private:20002" in prompt_text
    assert "私聊新问题" in prompt_text
    assert "私聊里的旧话" in prompt_text
    assert "群里的旧话" not in prompt_text
    assert "group:10001" in prompt_text


def test_targeted_replies_create_per_target_messages():
    runtime = _runtime_for_flow(
        [
            {
                "thought": "我把两个对象分开回应。",
                "decision": "reply",
                "reply_text": "",
                "targeted_replies": [
                    {"target": {"adapter": "napcat_qq", "message_type": "group", "group_id": "10001", "conversation_id": "group:10001"}, "text": "群里我看到了。"},
                    {"target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "20002", "conversation_id": "private:20002"}, "text": "银子，我单独回你。"},
                ],
                "tool_calls": [],
                "confidence": 0.8,
                "why": "multi target",
            },
            {"thought": "已经分别回应了。", "decision": "sleep", "reply_text": "", "tool_calls": [], "confidence": 0.8, "why": "done"},
        ],
        soft=2,
        hard=2,
    )

    result = runtime.send_message(
        {
            "text": "同时测试",
            "source": "napcat_qq",
            "conversation_id": "group:10001",
            "adapter_label": "群聊 10001",
            "reply_target": {"adapter": "napcat_qq", "message_type": "group", "group_id": "10001", "conversation_id": "group:10001", "target_label": "群聊 10001"},
        }
    )

    replies = result["replies"]
    assert [reply["conversation_id"] for reply in replies] == ["group:10001", "private:20002"]
    assert replies[0]["reply_target"]["message_type"] == "group"
    assert replies[1]["reply_target"]["message_type"] == "private"


def test_group_prompt_exposes_sender_private_and_active_group_targets():
    runtime = _runtime_for_flow(
        [
            {
                "thought": "我需要同时私聊和回群。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "prompt probe",
            }
        ],
        soft=1,
        hard=1,
    )

    runtime.send_message(
        {
            "text": "小澪给我发个私聊消息，然后再回这个群里面报告一下",
            "source": "napcat_qq",
            "conversation_id": "group:100010001",
            "adapter_label": "群聊 100010001 / 银子 (200020002)",
            "adapter_event": {
                "adapter": "napcat_qq",
                "message_type": "group",
                "group_id": "100010001",
                "user_id": "200020002",
                "sender": {"user_id": "200020002", "card": "银子"},
                "conversation_id": "group:100010001",
                "target_label": "群聊 100010001 / 银子 (200020002)",
            },
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": "group",
                "group_id": "100010001",
                "conversation_id": "group:100010001",
                "target_label": "群聊 100010001",
            },
        }
    )
    prompt_text = "\n".join(message["content"] for message in runtime.gateway.messages[-1])

    assert "available_reply_targets" in prompt_text
    assert "sender_private" in prompt_text
    assert "private:200020002" in prompt_text
    assert "active_group" in prompt_text
    assert "group:100010001" in prompt_text
    assert "先私聊我，再在群里报告" in prompt_text


def test_targeted_replies_without_reply_text_are_feedbacked_and_ingested():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我分成私聊和群聊两条发。",
                "decision": "reply",
                "reply_text": "",
                "targeted_replies": [
                    {"target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"}, "text": "我现在在整理照片素材。"},
                    {"target": {"adapter": "napcat_qq", "message_type": "group", "group_id": "100010001", "conversation_id": "group:100010001"}, "text": "私聊已经发啦。"},
                ],
                "tool_calls": [],
                "confidence": 0.86,
                "why": "multi target task",
            },
            {"thought": "两边都发过了。", "decision": "sleep", "reply_text": "", "tool_calls": [], "confidence": 0.82, "why": "done"},
        ],
        soft=2,
        hard=2,
    )
    dispatches = []

    result = runtime.send_message(
        {
            "text": "先私聊再回群",
            "source": "napcat_qq",
            "conversation_id": "group:100010001",
            "adapter_label": "群聊 100010001 / 银子 (200020002)",
            "reply_target": {"adapter": "napcat_qq", "message_type": "group", "group_id": "100010001", "conversation_id": "group:100010001"},
        },
        on_reply=lambda reply: dispatches.append(reply) or {"ok": True, "message_id": f"qq_{len(dispatches)}", "reply_id": reply.get("id")},
    )

    assert len(result["replies"]) == 2
    assert [reply["conversation_id"] for reply in result["replies"]] == ["private:200020002", "group:100010001"]
    assert len(dispatches) == 2
    assert any(
        report.get("tick_labels", {}).get("source") == "agent_reply_text"
        and "私聊已经发啦" in str(report.get("input_queue", {}).get("tick_text") or "")
        for report in getattr(runtime, "_cycle_reports", [])
    )


def test_napcat_rate_limit_is_scoped_per_reply_target(tmp_path, monkeypatch):
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: tmp_path / "agent_adapter_events.jsonl")
    monkeypatch.setattr("observatory.agent_runtime._outbox_path", lambda: tmp_path / "agent_outbox.jsonl")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.qq_napcat_enabled = True
    runtime.config.qq_napcat_dry_run = True
    runtime.config.qq_napcat_min_send_interval_ms = 60_000

    private = runtime.send_adapter_reply(
        {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        "私聊一条",
        reply_id="p1",
    )
    group = runtime.send_adapter_reply(
        {"adapter": "napcat_qq", "message_type": "group", "group_id": "100010001", "conversation_id": "group:100010001"},
        "群里一条",
        reply_id="g1",
    )
    private_again = runtime.send_adapter_reply(
        {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        "私聊第二条",
        reply_id="p2",
    )

    assert private["ok"] is True
    assert group["ok"] is True
    assert private_again["ok"] is False
    assert private_again["reason"] == "rate_limited"


def test_napcat_reply_auto_segments_by_custom_delimiter(tmp_path, monkeypatch):
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: tmp_path / "agent_adapter_events.jsonl")
    monkeypatch.setattr("observatory.agent_runtime._outbox_path", lambda: tmp_path / "agent_outbox.jsonl")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.qq_napcat_enabled = True
    runtime.config.qq_napcat_dry_run = True
    runtime.config.qq_napcat_min_send_interval_ms = 60_000
    runtime.config.reply_auto_segment_enabled = True
    runtime.config.reply_auto_segment_delimiter = "|"
    runtime.config.reply_segment_interval_mode = "fixed"
    runtime.config.reply_segment_fixed_interval_ms = 0
    runtime.config.reply_segment_interval_jitter = 0

    result = runtime.send_adapter_reply(
        {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        "好呀|我先看一下|等我几秒",
        reply_id="reply_seg",
    )

    assert result["ok"] is True
    assert result["segmented"] is True
    assert result["segments_text"] == ["好呀", "我先看一下", "等我几秒"]
    assert result["sent_segment_count"] == 3
    outbox = _read_jsonl_tail(tmp_path / "agent_outbox.jsonl", limit=10)
    assert [row["text"] for row in outbox] == ["好呀", "我先看一下", "等我几秒"]
    assert [row["reply_id"] for row in outbox] == ["reply_seg#1", "reply_seg#2", "reply_seg#3"]


def test_reply_auto_segment_uses_punctuation_but_not_comma():
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.reply_auto_segment_enabled = True
    runtime.config.reply_auto_segment_delimiter = ""
    runtime.config.reply_segment_target_chars = 4

    parts = runtime._split_reply_text_for_send("好呀，银子 我在。等我一下！")

    assert parts == ["好呀，银子", "我在。", "等我一下！"]


def test_reply_auto_segment_prompt_rule_is_reply_only():
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.reply_auto_segment_enabled = True
    runtime.config.reply_auto_segment_delimiter = "|"

    preview = runtime.prompt_preview({"text": "晚上好", "write_snapshot": False})
    prompt_text = "\n".join(message["content"] for message in preview["messages"])

    assert "回复自动分段已开启" in prompt_text
    assert "当前分段符是 \"|\"" in prompt_text
    assert "不作用于 thought" in prompt_text
    assert "reply_text=\"好呀|我先看一下|等我几秒\"" in prompt_text


def test_wait_ticks_credit_offsets_next_pre_llm_ticks():
    runtime = _fast_runtime_for_flow([], soft=4, hard=4)
    runtime.config.pre_thought_ticks = 3
    runtime.config.post_thought_ticks = 0
    runtime.config.run_ap_while_waiting_llm = True
    runtime.config.llm_wait_tick_interval_ms = 50
    runtime.config.llm_wait_tick_max_per_call = 3
    runtime.gateway = _WaitTickGateway(delay=1.05)

    result = runtime.send_message({"text": "你好", "_run_ap_while_waiting_llm": True, "_pre_thought_ticks_override": 3})
    sources = [_report_source(report) for report in result.get("ap_reports", [])]

    assert sources.count("agent_llm_wait_tick") >= 3
    assert sources.count("agent_pre_llm_tick") < 6
    assert result["turn"]["thought_runtime"]["llm_wait_tick_credit_final"] >= 3


def test_wait_tick_progress_carries_live_packet_and_reports():
    runtime = _fast_runtime_for_flow([], soft=3, hard=3)
    runtime.config.pre_thought_ticks = 2
    runtime.config.post_thought_ticks = 0
    runtime.config.run_ap_while_waiting_llm = True
    runtime.config.llm_wait_tick_interval_ms = 50
    runtime.gateway = _WaitTickGateway(delay=0.24)
    progress_rows = []

    runtime.send_message(
        {"text": "你好", "_run_ap_while_waiting_llm": True, "_pre_thought_ticks_override": 2},
        progress=lambda update: progress_rows.append(dict(update or {})),
    )

    wait_rows = [row for row in progress_rows if row.get("stage") == "waiting_llm_ap_tick"]
    assert wait_rows
    assert any(isinstance(row.get("ap_packet"), dict) and row["ap_packet"].get("summary") is not None for row in wait_rows)
    assert any(row.get("recent_reports") for row in wait_rows)
    ticks = [row.get("ap_packet", {}).get("tick_counter") for row in wait_rows]
    ers = [row.get("ap_packet", {}).get("summary", {}).get("total_er") for row in wait_rows]
    assert ticks == sorted(ticks)
    assert len(set(ticks)) == len(ticks)
    assert len(set(ers)) == len(ers)


def test_pre_llm_tick_progress_carries_latest_ap_packet_each_tick():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "前置 tick 刷新探针结束。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "progress packet probe",
            }
        ],
        soft=1,
        hard=1,
    )
    runtime.config.pre_thought_ticks = 4
    progress_rows = []

    runtime.send_message({"text": "检查每 tick 刷新"}, progress=lambda update: progress_rows.append(dict(update or {})))

    done_rows = [row for row in progress_rows if row.get("stage") == "pre_llm_tick_done"]
    ticks = [row.get("ap_packet", {}).get("tick_counter") for row in done_rows]
    ers = [row.get("ap_packet", {}).get("summary", {}).get("total_er") for row in done_rows]
    assert ticks == sorted(ticks)
    assert len(set(ticks)) == len(ticks)
    assert len(set(ers)) == len(ers)


def test_operator_stop_during_llm_wait_returns_sleep_without_waiting_for_llm():
    runtime = _fast_runtime_for_flow([], soft=4, hard=4)
    runtime.config.pre_thought_ticks = 2
    runtime.config.post_thought_ticks = 0
    runtime.config.run_ap_while_waiting_llm = True
    runtime.config.llm_wait_tick_interval_ms = 50
    runtime.gateway = _WaitTickGateway(delay=1.0)

    progress_rows = []
    stop_after_wait = {"armed": False}

    def progress(update):
        progress_rows.append(dict(update or {}))
        if update.get("stage") == "waiting_llm":
            stop_after_wait["armed"] = True

    result = runtime.send_message(
        {"text": "你好", "_run_ap_while_waiting_llm": True, "_pre_thought_ticks_override": 2},
        progress=progress,
        should_stop=lambda: bool(stop_after_wait["armed"]),
    )

    assert result["turn"]["decision"] == "sleep"
    assert not result["replies"]
    assert result["turn"]["llm_status"]["mode"] == "operator_stop"
    assert any(row.get("stage") == "operator_stopped" for row in progress_rows)


def test_external_input_during_llm_wait_enters_next_prompt_and_ap_tick():
    runtime = _fast_runtime_for_flow([], soft=4, hard=4)
    runtime.config.pre_thought_ticks = 1
    runtime.config.post_thought_ticks = 0
    runtime.config.run_ap_while_waiting_llm = True
    runtime.config.llm_wait_tick_interval_ms = 50
    runtime.gateway = _InterruptGateway()

    inserted = {"done": False}

    def progress(update):
        if update.get("stage") == "waiting_llm" and not inserted["done"]:
            inserted["done"] = True
            runtime.enqueue_external_input({"text": "你现在心情怎么样?", "source": "test"})

    result = runtime.send_message({"text": "第一条消息", "_run_ap_while_waiting_llm": True, "_pre_thought_ticks_override": 1}, progress=progress)
    sources = [_report_source(report) for report in result.get("ap_reports", [])]

    assert "agent_external_interrupt" in sources
    assert len(runtime.gateway.messages) >= 2
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "本轮思考中插入的新用户输入" in second_prompt
    assert "你现在心情怎么样" in second_prompt
    assert result["turn"]["thought_runtime"]["external_input_count_this_turn"] >= 1


def test_sleep_at_hard_limit_is_deferred_when_new_external_input_arrives():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我觉得第一条已经处理完了，准备停下。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "settled before late input",
            },
            {
                "thought": "刚才收束前又有新消息进来，我需要先看新消息。",
                "decision": "reply",
                "reply_text": "看到了，新的表情包消息也进来了。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "late external input",
            },
        ],
        soft=1,
        hard=1,
    )
    inserted = {"done": False}

    def progress(update):
        if update.get("stage") == "thought_ready" and not inserted["done"]:
            inserted["done"] = True
            runtime.enqueue_external_input(
                {
                    "text": "[image:[动画表情]]",
                    "source": "napcat_qq",
                    "id": "late_sticker",
                    "attachments": [{"kind": "image", "name": "动画表情.jpg", "file": "sticker-file", "sticker_like": True}],
                }
            )

    result = runtime.send_message({"text": "先处理这句"}, progress=progress)

    assert result["turn"]["decision"] == "reply"
    assert len(runtime.gateway.messages) >= 2
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "[image" in second_prompt or "动画表情" in second_prompt
    assert any("新的表情包消息" in str(item.get("text") or "") for item in result["replies"])


def test_sleep_is_deferred_when_new_message_is_in_state_but_not_pending():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我已经回复过上一张表情了，准备收束。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "no new input in prompt",
            },
            {
                "thought": "刚才收束前其实又有一张新图进来了，我需要先处理这张新图。",
                "decision": "reply",
                "reply_text": "看到了，新图也进来了。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "state watermark found late image",
            },
        ],
        soft=1,
        hard=1,
    )
    inserted = {"done": False}

    def progress(update):
        if update.get("stage") == "waiting_llm" and not inserted["done"]:
            inserted["done"] = True
            runtime.state["messages"].append(
                {
                    "id": "late_state_image",
                    "role": "user",
                    "text": "[image:[动画表情]]",
                    "source": "napcat_qq",
                    "conversation_id": "private:200020002",
                    "adapter_label": "私聊 银子 (200020002)",
                    "attachments": [
                        {"kind": "image", "name": "A24EE4EAD06EB6DC0018D734D90C52B0.jpg", "file": "A24EE4EAD06EB6DC0018D734D90C52B0.jpg", "sticker_like": True}
                    ],
                    "created_at_ms": 999999,
                }
            )

    result = runtime.send_message(
        {
            "text": "[image:[动画表情]]",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
        },
        progress=progress,
    )

    assert result["turn"]["decision"] == "reply"
    assert len(runtime.gateway.messages) >= 2
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "A24EE4EAD06EB6DC0018D734D90C52B0.jpg" in second_prompt
    assert any("新图也进来了" in str(item.get("text") or "") for item in result["replies"])


def test_multiple_external_inputs_are_integrated_without_overwriting_chat_timeline():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我先等一下，看看用户是不是还会补充信息。",
                "decision": "continue_thinking",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.7,
                "why": "wait for more input",
            },
            {
                "thought": "用户已经连续补充了名字和问题，我可以把这些一起接住。",
                "decision": "reply",
                "reply_text": "你好，银子，我是澪。刚刚你先和我打招呼，又告诉我你的名字，现在问我是谁，我就顺着这三句一起回答你。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "integrate multiple inputs",
            },
            {
                "thought": "我已经综合回应了这几条输入，先停下等他继续。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.85,
                "why": "settled",
            },
        ],
        soft=4,
        hard=5,
    )
    inserted = {"done": False}

    def progress(update):
        if update.get("stage") == "waiting_llm" and not inserted["done"]:
            inserted["done"] = True
            runtime.enqueue_external_input({"text": "我是银子", "source": "test", "id": "msg_name"})
            runtime.enqueue_external_input({"text": "你是谁", "source": "test", "id": "msg_who"})

    result = runtime.send_message({"text": "你好啊", "_message_id": "msg_hello"}, progress=progress)

    visible_texts = [str(item.get("text") or "") for item in result["messages"] if isinstance(item, dict)]
    assert "你好啊" in visible_texts
    assert "我是银子" in visible_texts
    assert "你是谁" in visible_texts
    assert any("你好，银子，我是澪" in str(item.get("text") or "") for item in result["replies"])
    second_prompt = runtime.gateway.messages[1][1]["content"]
    assert "发送者: User" in second_prompt
    assert "你好啊" in second_prompt
    assert "我是银子" in second_prompt
    assert "你是谁" in second_prompt
    assert result["turn"]["thought_runtime"]["external_input_count_this_turn"] >= 2


def test_napcat_group_reply_with_mentions_builds_onebot_at_segment(tmp_path, monkeypatch):
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: tmp_path / "agent_adapter_events.jsonl")
    monkeypatch.setattr("observatory.agent_runtime._outbox_path", lambda: tmp_path / "agent_outbox.jsonl")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.qq_napcat_enabled = True
    runtime.config.qq_napcat_dry_run = True
    runtime.config.qq_napcat_min_send_interval_ms = 0

    result = runtime.send_adapter_reply(
        {
            "adapter": "napcat_qq",
            "message_type": "group",
            "group_id": "100010001",
            "conversation_id": "group:100010001",
            "target_label": "群聊 测试讨论组2 (100010001)",
        },
        "这次补上",
        reply_id="group_at_1",
        mentions=["200020002"],
    )

    message = result["body_preview"]["message"]
    assert result["ok"] is True
    assert {"type": "at", "data": {"qq": "200020002"}} in message
    assert any(row.get("type") == "text" and "这次补上" in row.get("data", {}).get("text", "") for row in message)


def test_ordered_actions_can_group_at_then_private_confirm():
    runtime = _runtime_for_flow(
        [
            {
                "thought": "银子让我先去测试讨论组2艾特他，再回来私聊确认，我要把两个动作分开执行。",
                "decision": "reply",
                "reply_text": "",
                "actions": [
                    {
                        "type": "reply",
                        "target": {
                            "adapter": "napcat_qq",
                            "message_type": "group",
                            "group_id": "100010001",
                            "conversation_id": "group:100010001",
                            "target_label": "群聊 测试讨论组2 (100010001)",
                        },
                        "text": "银子",
                        "mentions": ["200020002"],
                    },
                    {
                        "type": "reply",
                        "target": {
                            "adapter": "napcat_qq",
                            "message_type": "private",
                            "user_id": "200020002",
                            "conversation_id": "private:200020002",
                            "target_label": "私聊 银子 (200020002)",
                        },
                        "text": "艾特好了",
                    },
                ],
                "tool_calls": [],
                "confidence": 0.9,
                "why": "multi action target task",
            },
            {"thought": "两个目标都已经处理过了，先停下。", "decision": "sleep", "reply_text": "", "tool_calls": [], "confidence": 0.85, "why": "done"},
        ],
        soft=2,
        hard=2,
    )
    dispatches = []

    result = runtime.send_message(
        {
            "text": "去隔壁群测试讨论组2里面艾特我一下，艾特成功以后再过来私聊说一声",
            "source": "napcat_qq",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        },
        on_reply=lambda reply: dispatches.append(reply) or {"ok": True, "message_id": f"qq_{len(dispatches)}", "reply_id": reply.get("id")},
    )

    assert [reply["conversation_id"] for reply in result["replies"]] == ["group:100010001", "private:200020002"]
    assert result["replies"][0]["mentions"] == ["200020002"]
    assert result["replies"][0]["adapter_dispatch"]["message_id"] == "qq_1"
    assert result["replies"][1]["adapter_dispatch"]["message_id"] == "qq_2"
    assert [row["conversation_id"] for row in dispatches] == ["group:100010001", "private:200020002"]


def test_prompt_exposes_recent_group_target_for_cross_context_action():
    runtime = _runtime_for_flow([], soft=2, hard=3)
    runtime.state["messages"].append(
        {
            "id": "recent_group_msg",
            "role": "user",
            "text": "小澪在不在",
            "source": "napcat_qq",
            "conversation_id": "group:100010001",
            "adapter_label": "群聊 测试讨论组2 (100010001) / 银子 (200020002)",
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": "group",
                "group_id": "100010001",
                "conversation_id": "group:100010001",
                "group_name": "测试讨论组2",
                "target_label": "群聊 测试讨论组2 (100010001)",
            },
            "adapter_event": {
                "adapter": "napcat_qq",
                "message_type": "group",
                "group_id": "100010001",
                "conversation_id": "group:100010001",
                "group_name": "测试讨论组2",
                "target_label": "群聊 测试讨论组2 (100010001) / 银子 (200020002)",
            },
            "created_at_ms": 1,
        }
    )

    runtime.send_message(
        {
            "text": "去隔壁群测试讨论组2里面艾特我一下",
            "source": "napcat_qq",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        }
    )
    prompt_text = "\n".join(message["content"] for message in runtime.gateway.messages[0])

    assert "recent_group" in prompt_text
    assert "测试讨论组2" in prompt_text
    assert "group:100010001" in prompt_text
    assert "mentions" in prompt_text


def test_same_turn_timeline_preserves_each_message_target_label():
    runtime = _fast_runtime_for_flow(
        [
            {
                "thought": "我先接住私聊。",
                "decision": "reply",
                "reply_text": "我在。",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "first",
            },
            {
                "thought": "群里插入了新的纠错，我要看清对象再处理。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "timeline probe",
            },
        ],
        soft=2,
        hard=3,
    )

    inserted = {"done": False}

    def progress(update):
        if update.get("stage") == "replying" and not inserted["done"]:
            inserted["done"] = True
            runtime.enqueue_external_input(
                {
                    "text": "@3255868832 你没有艾特我啊",
                    "source": "napcat_qq",
                    "conversation_id": "group:100010001",
                    "adapter_label": "群聊 测试讨论组2 (100010001) / 银子 (200020002)",
                    "adapter_event": {
                        "adapter": "napcat_qq",
                        "message_type": "group",
                        "group_id": "100010001",
                        "user_id": "200020002",
                        "sender": {"user_id": "200020002", "card": "银子"},
                        "conversation_id": "group:100010001",
                        "target_label": "群聊 测试讨论组2 (100010001) / 银子 (200020002)",
                    },
                    "reply_target": {
                        "adapter": "napcat_qq",
                        "message_type": "group",
                        "group_id": "100010001",
                        "conversation_id": "group:100010001",
                        "target_label": "群聊 测试讨论组2 (100010001)",
                    },
                }
            )

    runtime.send_message(
        {
            "text": "你在隔壁群艾特我一下",
            "source": "napcat_qq",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002", "target_label": "私聊 银子 (200020002)"},
        },
        progress=progress,
    )

    second_prompt = "\n".join(message["content"] for message in runtime.gateway.messages[1])
    assert "对象: 私聊 银子" in second_prompt
    assert "对象: 群聊 测试讨论组2 (100010001) / 银子 (200020002)" in second_prompt
    assert "你没有艾特我啊" in second_prompt


def test_prompt_exposes_cross_turn_outbox_proof_for_missing_group_at(monkeypatch, tmp_path):
    outbox_path = tmp_path / "agent_outbox.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._outbox_path", lambda: outbox_path)
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.state["outbound"] = {
        "adapter_replies": [
            {
                "ts": 1770000000000,
                "adapter": "napcat_qq",
                "endpoint": "http://127.0.0.1:3000/send_private_msg",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
                "text": "好了，银子，我在测试讨论组2里艾特你了~",
                "action_type": "reply",
                "mentions": [],
                "ok": True,
                "dry_run": False,
                "reply_id": "reply_private_only",
                "message_id": "qq_private_1",
            }
        ]
    }

    runtime.send_message(
        {
            "text": "@3255868832 你没有艾特我啊",
            "source": "napcat_qq",
            "conversation_id": "group:100010001",
            "adapter_label": "群聊 测试讨论组2 (100010001) / 银子 (200020002)",
            "adapter_event": {
                "adapter": "napcat_qq",
                "message_type": "group",
                "group_id": "100010001",
                "user_id": "200020002",
                "sender": {"user_id": "200020002", "card": "银子"},
                "conversation_id": "group:100010001",
                "target_label": "群聊 测试讨论组2 (100010001) / 银子 (200020002)",
            },
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": "group",
                "group_id": "100010001",
                "conversation_id": "group:100010001",
                "target_label": "群聊 测试讨论组2 (100010001)",
            },
        }
    )
    prompt_text = "\n".join(message["content"] for message in runtime.gateway.messages[0])

    assert "近期真实外发凭证（跨轮）" in prompt_text
    assert "private:200020002" in prompt_text
    assert "qq_private_1" in prompt_text
    assert "没有对应目标的 ok=true 记录，应立即承认漏了并补发 action" in prompt_text
    assert "group:100010001" in prompt_text
    assert "mentions" in prompt_text


def test_image_understanding_receives_attachment_and_context(monkeypatch, tmp_path):
    image_path = tmp_path / "screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nunit")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = "test-key"
    runtime.config.multimodal_model = "vision-test"
    runtime.state["messages"].append(
        {
            "id": "image_msg",
            "role": "user",
            "text": "[image:screen.png] 你能看见截图内容吗",
            "conversation_id": "private:200020002",
            "attachments": [{"kind": "image", "id": "screen", "name": "screen.png", "file": str(image_path)}],
            "created_at_ms": 1,
        }
    )
    captured = {}

    def fake_generate_text(messages, model="", purpose="", max_tokens=None, response_format=None):
        captured["messages"] = messages
        captured["model"] = model
        return "图片里是一个调试截图，关键是用户在问截图是否能被读取。", {"ok": True, "mode": "fake_vision"}

    monkeypatch.setattr(runtime.gateway, "generate_text", fake_generate_text, raising=False)
    result = runtime.tools.run("image_understanding", {"attachment_id": "screen", "question": "截图里有什么", "context": "用户正在测试读图"}, source="unit")

    assert result["ok"] is True
    assert "调试截图" in result["output"]["summary"]
    assert captured["model"] == "vision-test"
    assert "用户正在测试读图" in captured["messages"][1]["content"][0]["text"]


def test_image_understanding_resolves_napcat_file_id_with_get_image(monkeypatch, tmp_path):
    image_path = tmp_path / "napcat_screen.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nunit")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = "test-key"
    runtime.config.multimodal_model = "vision-test"
    runtime.config.qq_napcat_http_url = "http://127.0.0.1:3000"
    runtime.state["messages"].append(
        {
            "id": "image_msg",
            "role": "user",
            "text": "[image:abc.png] 看这个",
            "conversation_id": "private:200020002",
            "attachments": [{"kind": "image", "id": "abc-file-id", "name": "abc.png", "file": "abc-file-id"}],
            "created_at_ms": 1,
        }
    )
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"status": "ok", "data": {"file": str(image_path)}}, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    def fake_generate_text(messages, model="", purpose="", max_tokens=None, response_format=None):
        captured["vision_messages"] = messages
        return "截图可以读取，内容和当前调试任务相关。", {"ok": True, "mode": "fake_vision"}

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(runtime.gateway, "generate_text", fake_generate_text, raising=False)

    result = runtime.tools.run("image_understanding", {"attachment_id": "abc-file-id", "question": "能看见吗"}, source="unit")

    assert result["ok"] is True
    assert captured["url"].endswith("/get_image")
    assert captured["body"] == {"file": "abc-file-id"}
    assert "截图可以读取" in result["output"]["summary"]
    assert result["output"]["attachment"]["napcat_get_image"]["ok"] is True


def test_image_understanding_matches_current_file_not_old_duplicate_id(monkeypatch, tmp_path):
    old_path = tmp_path / "old-cat.png"
    new_path = tmp_path / "A9798DD8AA185EDC1CF7E80277D4732C.jpg"
    old_path.write_bytes(b"\x89PNG\r\n\x1a\nold-cat")
    new_path.write_bytes(b"\xff\xd8new-sticker")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = "test-key"
    runtime.config.multimodal_model = "vision-test"
    runtime.state["messages"].extend(
        [
            {
                "id": "old",
                "role": "user",
                "text": "[image:old]",
                "conversation_id": "private:200020002",
                "attachments": [{"kind": "image", "id": "image_0", "name": "old-cat.png", "file": str(old_path), "sticker_like": True}],
                "created_at_ms": 1,
            },
            {
                "id": "new",
                "role": "user",
                "text": "[image:[动画表情]]",
                "conversation_id": "private:200020002",
                "attachments": [
                    {
                        "kind": "image",
                        "id": "image_0",
                        "name": "A9798DD8AA185EDC1CF7E80277D4732C.jpg",
                        "file": str(new_path),
                        "sticker_like": True,
                    }
                ],
                "created_at_ms": 2,
            },
        ]
    )
    captured = {}

    def fake_generate_text(messages, model="", purpose="", max_tokens=None, response_format=None):
        captured["messages"] = messages
        return "这是新发的早上好表情包。", {"ok": True, "mode": "fake_vision"}

    monkeypatch.setattr(runtime.gateway, "generate_text", fake_generate_text, raising=False)
    result = runtime.tools.run(
        "image_understanding",
        {"attachment_id": "A9798DD8AA185EDC1CF7E80277D4732C.jpg", "question": "这张表情是什么"},
        source="unit",
    )

    assert result["ok"] is True
    assert result["output"]["attachment"]["file"] == str(new_path)
    image_part = captured["messages"][1]["content"][1]
    assert base64.b64decode(image_part["image_url"]["url"].split(",", 1)[1]).endswith(b"new-sticker")


def test_attachment_summary_includes_current_file_identity():
    summary = _attachment_summary(
        [
            {
                "kind": "image",
                "id": "image_0",
                "name": "A9798DD8AA185EDC1CF7E80277D4732C.jpg",
                "file": "A9798DD8AA185EDC1CF7E80277D4732C.jpg",
                "url": "https://multimedia.nt.qq.com.cn/download?appid=abc",
                "sticker_like": True,
                "source_fields": {"md5": "A9798D", "sub_type": "1"},
            }
        ]
    )

    assert "image_0" in summary
    assert "A9798DD8AA185EDC1CF7E80277D4732C.jpg" in summary
    assert "multimedia.nt.qq.com.cn" in summary
    assert "md5=A9798D" in summary
    assert "sub_type=1" in summary


def test_attachment_preview_returns_data_url_for_napcat_image(monkeypatch, tmp_path):
    image_path = tmp_path / "preview.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nunit-preview")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = ""
    runtime.config.qq_napcat_http_url = "http://127.0.0.1:3000"
    captured = {}

    class FakeResp:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"status": "ok", "data": {"file": str(image_path)}}, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    result = runtime.preview_attachments(
        {
            "attachments": [
                {"kind": "image", "id": "napcat-file-id", "name": "表情.png", "file": "napcat-file-id"},
            ]
        }
    )

    assert result["previews"][0]["ok"] is True
    assert result["previews"][0]["src"].startswith("data:image/png;base64,")
    assert captured["url"].endswith("/get_image")
    assert captured["body"] == {"file": "napcat-file-id"}


def test_attachment_preview_default_does_not_call_vision(monkeypatch, tmp_path):
    image_path = tmp_path / "preview.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nunit-preview")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = "test-key"
    runtime.config.multimodal_model = "vision-test"

    def fail_generate_text(*args, **kwargs):
        raise AssertionError("default attachment preview must not call external vision model")

    monkeypatch.setattr(runtime.gateway, "generate_text", fail_generate_text, raising=False)

    result = runtime.preview_attachments({"attachments": [{"kind": "image", "name": "普通图.png", "file": str(image_path)}]})

    assert result["ok"] is True
    assert result["external_api_called"] is False
    assert result["side_effects"] == "local_preview_only"
    assert result["vision_strategy"]["mode"] == "preview_only"
    assert result["vision_tool_results"] == []


def test_attachment_preview_include_vision_calls_vision(monkeypatch, tmp_path):
    image_path = tmp_path / "preview.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nunit-preview")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = "test-key"
    runtime.config.multimodal_model = "vision-test"
    calls = {"count": 0}

    def fake_generate_text(messages, model="", purpose="", max_tokens=None, response_format=None):
        calls["count"] += 1
        return "图片里是一个测试预览。", {"ok": True, "mode": "fake_vision"}

    monkeypatch.setattr(runtime.gateway, "generate_text", fake_generate_text, raising=False)

    result = runtime.preview_attachments({"include_vision": True, "attachments": [{"kind": "image", "name": "普通图.png", "file": str(image_path)}]})

    assert result["external_api_called"] is True
    assert result["vision_strategy"]["include_vision"] is True
    assert result["vision_tool_results"][0]["ok"] is True
    assert calls["count"] == 1


def test_image_generation_uses_dedicated_key_and_cooldown(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://provider.test",
            "api_key": "main-key",
            "image_generation_api_key": "draw-key",
            "image_generation_model": "draw-model",
            "retry_count": 0,
        }
    )
    gateway = LLMGateway(config)
    captured = {"calls": 0, "auth": ""}

    def fake_urlopen(req, timeout=None):
        captured["calls"] += 1
        captured["auth"] = req.headers.get("Authorization") or req.headers.get("authorization") or ""
        raise OSError("provider down")

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    first_raw, first_status = gateway.generate_image(prompt="画一张图")
    second_raw, second_status = gateway.generate_image(prompt="画一张图")
    third_raw, third_status = gateway.generate_image(prompt="画一张图")

    assert first_raw == {}
    assert first_status["reason"] == "image_generation_failed"
    assert captured["auth"] == "Bearer draw-key"
    assert second_raw == {}
    assert second_status["reason"] == "image_generation_failed"
    assert third_raw == {}
    assert third_status["reason"] == "image_generation_cooldown"
    assert third_status["cooldown"]["cooldown_ms"] == 3000
    assert captured["calls"] == 2


def test_image_generation_blank_dedicated_key_reuses_main_key(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://provider.test",
            "api_key": "main-key",
            "image_generation_api_key": "",
            "image_generation_model": "draw-model",
        }
    )
    gateway = LLMGateway(config)
    captured = {"auth": "", "body": {}}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"data": []}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["auth"] = req.headers.get("Authorization") or req.headers.get("authorization") or ""
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    raw, status = gateway.generate_image(prompt="画一张图")

    assert status["ok"] is True
    assert raw == {"data": []}
    assert captured["auth"] == "Bearer main-key"
    assert captured["body"]["model"] == "draw-model"


def test_llm_gateway_retry_backoff_logs_and_circuit_breaker(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://provider.test",
            "api_key": "main-key",
            "model": "chat-model",
            "retry_count": 3,
        }
    )
    events = []
    sleeps = []
    gateway = LLMGateway(config, logger=lambda row: events.append(dict(row)))
    calls = {"count": 0}

    def fake_call(messages):
        calls["count"] += 1
        raise OSError("provider down")

    monkeypatch.setattr(gateway, "_call_chat_completions", fake_call)
    monkeypatch.setattr("observatory.agent_runtime.time.sleep", lambda seconds: sleeps.append(seconds))

    raw, status = gateway.generate([{"role": "user", "content": "hello"}])
    again_raw, again_status = gateway.generate([{"role": "user", "content": "hello"}])

    assert raw == {}
    assert status["reason"] == "llm_call_failed"
    assert calls["count"] == 4
    assert sleeps == [3.0, 6.0]
    assert any(row.get("event") == "llm_call_retry_scheduled" and row.get("delay_ms") == 0 for row in events)
    assert any(row.get("event") == "llm_call_retry_scheduled" and row.get("delay_ms") == 3000 for row in events)
    assert any(row.get("event") == "llm_call_retry_scheduled" and row.get("delay_ms") == 6000 for row in events)
    assert again_raw == {}
    assert again_status["mode"] == "cooldown"
    assert again_status["cooldown"]["cooldown_ms"] == 12000
    assert calls["count"] == 4

    key = gateway._cooldown_key(model=config.model, api_key=config.api_key, purpose="chat", endpoint="/v1/chat/completions")
    LLMGateway._failure_cooldowns[key] = {"count": 8, "until_ms": 0, "cooldown_ms": 0, "error": "still down", "model": config.model, "purpose": "chat"}
    sleeps.clear()
    fused_raw, fused_status = gateway.generate([{"role": "user", "content": "hello"}])

    assert fused_raw == {}
    assert fused_status["reason"] == "llm_circuit_open"
    assert fused_status["mode"] == "fused"
    assert fused_status["cooldown"]["fused"] is True
    assert calls["count"] == 8
    assert sleeps == [3.0, 6.0]
    assert any(row.get("event") == "llm_circuit_open" for row in events)


def test_llm_gateway_openai_compatible_claude_keeps_openai_vision_blocks(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://provider.test",
            "api_key": "main-key",
            "multimodal_model": "claude-3-5-sonnet-latest",
            "retry_count": 0,
        }
    )
    gateway = LLMGateway(config)
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    content, status = gateway.generate_text(
        [
            {"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
        ],
        purpose="vision",
    )

    image_part = captured["body"]["messages"][0]["content"][1]
    assert status["ok"] is True
    assert content == "ok"
    assert captured["url"] == "https://provider.test/v1/chat/completions"
    assert image_part == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}


def test_llm_gateway_openai_compatible_claude_omits_json_response_format(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://provider.test",
            "api_key": "main-key",
            "model": "claude-3-5-sonnet-latest",
            "retry_count": 0,
        }
    )
    gateway = LLMGateway(config)
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"choices": [{"message": {"content": "{\"thought\":\"ok\",\"decision\":\"sleep\",\"reply_text\":\"\"}"}}]}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    payload, status = gateway.generate([{"role": "user", "content": "输出 JSON"}])

    assert status["ok"] is True
    assert payload["thought"] == "ok"
    assert "response_format" not in captured["body"]


def test_llm_gateway_keeps_openai_vision_content_blocks_for_gpt_model(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://provider.test",
            "api_key": "main-key",
            "multimodal_model": "gpt-4.1-mini",
            "retry_count": 0,
        }
    )
    gateway = LLMGateway(config)
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"choices": [{"message": {"content": "ok"}}]}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    gateway.generate_text(
        [
            {"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}]},
        ],
        purpose="vision",
    )

    image_part = captured["body"]["messages"][0]["content"][1]
    assert image_part == {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}}


def test_llm_gateway_direct_anthropic_endpoint_uses_messages_api(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://api.anthropic.com",
            "api_key": "anthropic-key",
            "multimodal_model": "claude-3-5-sonnet-latest",
            "retry_count": 0,
        }
    )
    gateway = LLMGateway(config)
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"content": [{"type": "text", "text": "看到了"}], "usage": {"input_tokens": 1}}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    content, status = gateway.generate_text(
        [
            {"role": "system", "content": "只说中文"},
            {"role": "user", "content": [{"type": "text", "text": "看图"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,QUJD"}}]},
        ],
        purpose="vision",
        max_tokens=99,
    )

    assert status["ok"] is True
    assert status["mode"] == "anthropic_messages"
    assert content == "看到了"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["X-api-key"] == "anthropic-key"
    assert captured["headers"]["Anthropic-version"] == "2023-06-01"
    assert captured["body"]["system"] == "只说中文"
    assert captured["body"]["max_tokens"] == 99
    assert captured["body"]["messages"][0]["content"][1] == {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": "QUJD"}}


def test_llm_gateway_direct_anthropic_chat_parses_agent_json(monkeypatch):
    LLMGateway._failure_cooldowns.clear()
    config = AgentConfig.from_dict(
        {
            "llm_enabled": True,
            "base_url": "https://api.anthropic.com/v1",
            "api_key": "anthropic-key",
            "model": "claude-3-5-sonnet-latest",
            "retry_count": 0,
        }
    )
    gateway = LLMGateway(config)
    captured = {}

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            text = json.dumps({"thought": "在思考", "decision": "sleep", "reply_text": ""}, ensure_ascii=False)
            return json.dumps({"content": [{"type": "text", "text": text}]}).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["headers"] = dict(req.headers)
        captured["body"] = json.loads(req.data.decode("utf-8"))
        return FakeResp()

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    raw, status = gateway.generate(
        [
            {"role": "system", "content": "只输出 JSON"},
            {"role": "user", "content": "继续思考"},
        ]
    )

    assert status["ok"] is True
    assert status["mode"] == "anthropic_messages"
    assert raw["decision"] == "sleep"
    assert raw["thought"] == "在思考"
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["X-api-key"] == "anthropic-key"
    assert captured["body"]["system"] == "只输出 JSON"
    assert captured["body"]["messages"] == [{"role": "user", "content": "继续思考"}]


def test_attachment_preview_resolve_failure_is_cached_and_not_logged(monkeypatch, tmp_path):
    adapter_log = tmp_path / "agent_adapter_events.jsonl"
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: adapter_log)
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.api_key = ""
    runtime.config.qq_napcat_http_url = "http://127.0.0.1:3000"
    calls = {"count": 0}

    def fake_urlopen(req, timeout=None):
        calls["count"] += 1
        raise OSError("napcat image not ready")

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)

    payload = {"attachments": [{"kind": "image", "id": "missing-file-id", "name": "missing.png", "file": "missing-file-id"}]}
    first = runtime.preview_attachments(payload)
    second = runtime.preview_attachments(payload)
    events = runtime.adapter_events(limit=20, view="detail")["events"]

    assert first["previews"][0]["ok"] is False
    assert second["previews"][0]["ok"] is False
    assert calls["count"] == 1
    assert not [row for row in events if row.get("event") == "adapter_image_resolve_failed"]


def test_attachment_preview_does_not_trigger_sticker_steal(monkeypatch, tmp_path):
    image_path = tmp_path / "preview.png"
    image_path.write_bytes(b"\x89PNG\r\n\x1a\nunit-preview")
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.sticker_steal_enabled = True
    runtime.config.api_key = "test-key"
    runtime.config.multimodal_model = "vision-test"
    runtime.config.qq_napcat_http_url = "http://127.0.0.1:3000"

    class FakeResp:
        headers = {"Content-Type": "application/json"}

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self, *args):
            return json.dumps({"status": "ok", "data": {"file": str(image_path)}}, ensure_ascii=False).encode("utf-8")

    def fake_urlopen(req, timeout=None):
        return FakeResp()

    def fake_generate_text(messages, model="", purpose="", max_tokens=None, response_format=None):
        return "这是一张适合保存为表情包的图片。", {"ok": True, "mode": "fake_vision"}

    def fail_steal(*args, **kwargs):
        raise AssertionError("attachment preview must not save stickers")

    monkeypatch.setattr("observatory.agent_runtime.urllib.request.urlopen", fake_urlopen)
    monkeypatch.setattr(runtime.gateway, "generate_text", fake_generate_text, raising=False)
    monkeypatch.setattr(runtime, "_maybe_steal_sticker_from_vision", fail_steal)

    result = runtime.preview_attachments({"include_vision": True, "attachments": [{"kind": "image", "name": "普通图.png", "file": "napcat-file-id"}]})

    assert result["previews"][0]["ok"] is True
    assert result["vision_tool_results"][0]["ok"] is True


def test_napcat_animated_sticker_segment_is_image_attachment_with_source_fields():
    runtime = _runtime_for_flow([], soft=1, hard=1)

    normalized = runtime._normalize_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子"},
            "message": [
                {
                    "type": "mface",
                    "data": {
                        "summary": "[动画表情]",
                        "file": "68D3B0DDA8DF99AC3F1E2058570E3064.jpg",
                        "url": "https://example.test/sticker.jpg",
                        "md5": "68D3",
                    },
                }
            ],
        }
    )

    assert normalized["text"] == "[image:[动画表情]]"
    assert normalized["attachments"][0]["kind"] == "image"
    assert normalized["attachments"][0]["sticker_like"] is True
    assert normalized["attachments"][0]["file"] == "68D3B0DDA8DF99AC3F1E2058570E3064.jpg"
    assert normalized["attachments"][0]["url"] == "https://example.test/sticker.jpg"
    assert normalized["attachments"][0]["source_fields"]["md5"] == "68D3"


def test_sticker_steal_skips_plain_image_before_vision(monkeypatch):
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.sticker_steal_enabled = True
    captured_logs = []

    def fail_run(*args, **kwargs):
        raise AssertionError("plain image should not call vision sticker steal")

    monkeypatch.setattr(runtime.tools, "run", fail_run)
    monkeypatch.setattr(runtime, "record_adapter_log", lambda payload: captured_logs.append(dict(payload)) or payload)
    runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子"},
            "message": [{"type": "image", "data": {"file": "plain_screenshot.png", "filename": "截图.png"}}],
        }
    )

    assert any(row.get("event") == "adapter_sticker_steal_precheck_skipped" and row.get("reason") == "not_sticker_candidate" for row in captured_logs)


def test_sticker_steal_passes_latest_sticker_attachment_to_vision(monkeypatch):
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.sticker_steal_enabled = True
    captured = {}

    def fake_run(name, args=None, source="manual_tool"):
        captured["name"] = name
        captured["args"] = args or {}
        captured["source"] = source
        return {"ok": True, "tool": name, "output": {"summary": "适合保存为表情包。"}}

    monkeypatch.setattr(runtime.tools, "run", fake_run)
    runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子"},
            "message": [{"type": "image", "data": {"file": "90BC0E44260CF5906F1D8D9FEE35E097.jpg", "summary": "[动画表情]", "url": "https://example.test/latest.jpg", "sub_type": "1"}}],
        }
    )

    assert captured["name"] == "image_understanding"
    assert captured["source"] == "adapter_sticker_steal"
    assert captured["args"]["attachment"]["file"] == "90BC0E44260CF5906F1D8D9FEE35E097.jpg"
    assert captured["args"]["file"] == "90BC0E44260CF5906F1D8D9FEE35E097.jpg"
    assert captured["args"]["url"] == "https://example.test/latest.jpg"


def test_sticker_steal_result_is_preloaded_into_same_turn_prompt(monkeypatch):
    runtime = _runtime_for_flow(
        [
            {
                "thought": "我已经读到这张新表情是早上好，不沿用旧图记忆。",
                "decision": "reply",
                "reply_text": "早上好hhh",
                "tool_calls": [],
                "confidence": 0.9,
                "why": "vision result used",
            },
            {
                "thought": "已经回应过这张表情了，先停一下。",
                "decision": "sleep",
                "reply_text": "",
                "tool_calls": [],
                "confidence": 0.8,
                "why": "settled",
            },
        ],
        soft=2,
        hard=3,
    )
    runtime.config.sticker_steal_enabled = True
    captured = {}

    def fake_run(name, args=None, source="manual_tool"):
        captured["name"] = name
        captured["args"] = args or {}
        return {
            "ok": True,
            "tool": name,
            "output": {
                "ok": True,
                "mode": "vision_model",
                "summary": "当前新图是写着“早上好”的表情包，不是猫猫摸头。",
                "attachment": args.get("attachment"),
            },
        }

    monkeypatch.setattr(runtime.tools, "run", fake_run)
    runtime.ingest_adapter_event(
        {
            "adapter": "napcat_qq",
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子"},
            "message": [
                {
                    "type": "image",
                    "data": {
                        "file": "A9798DD8AA185EDC1CF7E80277D4732C.jpg",
                        "summary": "[动画表情]",
                        "url": "https://example.test/morning.jpg",
                        "sub_type": "1",
                    },
                }
            ],
        }
    )

    first_prompt = "\n".join(message["content"] for message in runtime.gateway.messages[0])
    assert captured["name"] == "image_understanding"
    assert captured["args"]["attachment"]["file"] == "A9798DD8AA185EDC1CF7E80277D4732C.jpg"
    assert "当前新图是写着“早上好”的表情包" in first_prompt
    assert "A9798DD8AA185EDC1CF7E80277D4732C.jpg" in first_prompt
    assert "当前用户附件工具参数建议" in first_prompt


def test_sticker_steal_dedupes_by_content_hash(monkeypatch, tmp_path):
    catalog_path = tmp_path / "agent_stickers.json"
    sticker_dir = tmp_path / "stickers"
    source_path = tmp_path / "thanks.png"
    source_path.write_bytes(b"\x89PNG\r\n\x1a\nsame-sticker")
    monkeypatch.setattr("observatory.agent_runtime._stickers_catalog_path", lambda: catalog_path)
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.sticker_steal_enabled = True
    runtime.config.sticker_library_dir = str(sticker_dir)
    attachment = {"kind": "image", "name": "谢谢.png", "file": str(source_path), "sticker_like": True, "source_fields": {"md5": "same-md5"}}

    first = runtime._maybe_steal_sticker_from_vision(args={"source": "unit", "sticker_source_fingerprint": "same-source"}, attachment=attachment, vision_summary="这是谢谢表情包，适合保存为表情包。")
    second = runtime._maybe_steal_sticker_from_vision(args={"source": "unit", "sticker_source_fingerprint": "same-source"}, attachment=attachment, vision_summary="这是谢谢表情包，适合保存为表情包。")

    assert first["ok"] is True
    assert second["ok"] is False
    assert second["reason"] in {"duplicate_source", "duplicate_content"}
    catalog = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert len(catalog["stickers"]) == 1
    assert catalog["stickers"][0]["content_sha256"]
    assert len(list(sticker_dir.glob("*"))) == 1


def test_sticker_catalog_sync_removes_missing_files_and_delete_clears_file(monkeypatch, tmp_path):
    catalog_path = tmp_path / "agent_stickers.json"
    sticker_path = tmp_path / "keep.png"
    missing_path = tmp_path / "missing.png"
    sticker_path.write_bytes(b"png")
    monkeypatch.setattr("observatory.agent_runtime._stickers_catalog_path", lambda: catalog_path)
    runtime = _runtime_for_flow([], soft=1, hard=1)
    catalog_path.write_text(
        json.dumps(
            {
                "stickers": [
                    {"id": "keep", "name": "保留", "path": str(sticker_path), "meaning": "ok"},
                    {"id": "gone", "name": "已删", "path": str(missing_path), "meaning": "gone"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    public = runtime.stickers_public()
    after_sync = json.loads(catalog_path.read_text(encoding="utf-8"))
    deleted = runtime.delete_sticker({"id": "keep"})

    assert public["sync"]["removed_missing"] == 1
    assert [item["id"] for item in after_sync["stickers"]] == ["keep"]
    assert deleted["deleted_count"] == 1
    assert not sticker_path.exists()
    assert json.loads(catalog_path.read_text(encoding="utf-8"))["stickers"] == []


def test_send_sticker_action_creates_image_attachment_and_marks_usage(tmp_path, monkeypatch):
    catalog_path = tmp_path / "agent_stickers.json"
    sticker_path = tmp_path / "笑死.png"
    sticker_path.write_bytes(b"png")
    monkeypatch.setattr("observatory.agent_runtime._stickers_catalog_path", lambda: catalog_path)
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: tmp_path / "agent_adapter_events.jsonl")
    monkeypatch.setattr("observatory.agent_runtime._outbox_path", lambda: tmp_path / "agent_outbox.jsonl")
    runtime = _runtime_for_flow(
        [
            {
                "thought": "这句适合轻轻丢个笑死表情。",
                "decision": "reply",
                "reply_text": "",
                "actions": [
                    {
                        "type": "send_sticker",
                        "target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
                        "sticker_id": "sticker_laugh",
                    }
                ],
                "tool_calls": [],
                "confidence": 0.86,
                "why": "sticker action",
            },
            {"thought": "表情已经发过了，停一下。", "decision": "sleep", "reply_text": "", "tool_calls": [], "confidence": 0.82, "why": "done"},
        ],
        soft=2,
        hard=2,
    )
    runtime.config.qq_napcat_enabled = True
    runtime.config.qq_napcat_dry_run = True
    runtime.config.qq_napcat_min_send_interval_ms = 0
    catalog_path.write_text(
        json.dumps({"stickers": [{"id": "sticker_laugh", "name": "笑死", "path": str(sticker_path), "meaning": "笑死/乐", "use_count": 0}]}, ensure_ascii=False),
        encoding="utf-8",
    )

    def on_reply(reply):
        return runtime.send_adapter_reply(
            reply.get("reply_target") or {},
            str(reply.get("text") or ""),
            reply_id=str(reply.get("id") or ""),
            attachments=reply.get("attachments") if isinstance(reply.get("attachments"), list) else None,
            action_type=str(reply.get("action_type") or "reply"),
            sticker_id=str(reply.get("sticker_id") or ""),
        )

    result = runtime.send_message(
        {
            "text": "发表情包",
            "source": "napcat_qq",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        },
        on_reply=on_reply,
    )

    assert result["replies"][0]["action_type"] == "send_sticker"
    assert result["replies"][0]["attachments"]
    assert result["adapter_replies"][0]["ok"] is True
    updated = json.loads(catalog_path.read_text(encoding="utf-8"))
    assert updated["stickers"][0]["use_count"] == 1


def test_image_generation_returns_reviewed_attachment(monkeypatch, tmp_path):
    runtime = _runtime_for_flow([], soft=1, hard=1)
    image_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
    )
    runtime.config.image_generation_model = "unit-image-model"
    runtime.config.multimodal_model = "unit-vision-model"
    runtime.config.vision_model = "unit-vision-model"
    captured = {}

    def fake_generate_image(prompt="", model="", size="1024x1024"):
        captured["image_prompt"] = prompt
        captured["image_model"] = model
        return {"data": [{"b64_json": base64.b64encode(image_bytes).decode("ascii")}]} , {"ok": True, "mode": "fake_image", "model": model or "unit-image-model"}

    def fake_generate_text(messages, model="", purpose="", max_tokens=None, response_format=None):
        captured["vision_messages"] = messages
        return "这张图基本符合用户想测试发图的要求，建议发送。", {"ok": True, "mode": "fake_vision", "model": model}

    monkeypatch.setattr(runtime.gateway, "generate_image", fake_generate_image, raising=False)
    monkeypatch.setattr(runtime.gateway, "generate_text", fake_generate_text, raising=False)

    result = runtime.tools.run(
        "image_generation",
        {
            "prompt": "小澪风格的虚拟自拍，黑发，居家，可爱但低调",
            "context": "银子想测试多模态绘图功能，希望发送一张图片。",
            "size": "1024x1024",
        },
        source="unit",
    )

    output = result["output"]
    assert result["ok"] is True
    assert output["attachment"]["kind"] == "image"
    assert Path(output["path"]).exists()
    assert Path(output["path"]).read_bytes() == image_bytes
    assert output["image_decode"]["offset"] == 0
    assert output["review"]["send_recommendation"] == "send"
    assert output["send_recommendation"] == "send"
    assert "send_image" in json.dumps(output["send_image_action_template"], ensure_ascii=False)
    assert "测试多模态绘图功能" in str(captured["vision_messages"])


def test_image_generation_strips_provider_prefix_before_png(monkeypatch):
    runtime = _runtime_for_flow([], soft=1, hard=1)
    image_bytes = base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
    )
    prefixed = b"provider-prefix!" + image_bytes
    runtime.config.image_generation_model = "unit-image-model"
    runtime.config.image_generation_review_enabled = False

    def fake_generate_image(prompt="", model="", size="1024x1024"):
        return {"data": [{"b64_json": base64.b64encode(prefixed).decode("ascii")}]} , {"ok": True, "mode": "fake_image", "model": model or "unit-image-model"}

    monkeypatch.setattr(runtime.gateway, "generate_image", fake_generate_image, raising=False)

    result = runtime.tools.run("image_generation", {"prompt": "一张测试图"}, source="unit")
    output = result["output"]

    assert result["ok"] is True
    assert Path(output["path"]).suffix == ".png"
    assert Path(output["path"]).read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
    assert Path(output["path"]).read_bytes() == image_bytes
    assert output["image_decode"]["offset"] == len(b"provider-prefix!")


def test_image_generation_rejects_invalid_image_bytes(monkeypatch):
    runtime = _runtime_for_flow([], soft=1, hard=1)
    runtime.config.image_generation_model = "unit-image-model"

    def fake_generate_image(prompt="", model="", size="1024x1024"):
        return {"data": [{"b64_json": base64.b64encode(b"not-an-image-at-all").decode("ascii")}]} , {"ok": True, "mode": "fake_image", "model": model or "unit-image-model"}

    monkeypatch.setattr(runtime.gateway, "generate_image", fake_generate_image, raising=False)

    result = runtime.tools.run("image_generation", {"prompt": "一张坏图"}, source="unit")

    assert result["ok"] is False
    assert result["output"]["error"] == "image_signature_not_found"
    assert "有效图片文件头" in result["output"]["summary"]


def test_send_image_action_builds_onebot_image_segment(tmp_path, monkeypatch):
    monkeypatch.setattr("observatory.agent_runtime._adapter_log_path", lambda: tmp_path / "agent_adapter_events.jsonl")
    monkeypatch.setattr("observatory.agent_runtime._outbox_path", lambda: tmp_path / "agent_outbox.jsonl")
    image_path = tmp_path / "generated.png"
    image_path.write_bytes(b"png")
    runtime = _runtime_for_flow(
        [
            {
                "thought": "生成图已经审核通过，我现在把图片发给银子。",
                "decision": "reply",
                "reply_text": "",
                "actions": [
                    {
                        "type": "send_image",
                        "target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
                        "text": "整好了，看看这个行不行",
                        "attachments": [{"kind": "image", "file": str(image_path), "name": "generated.png"}],
                    }
                ],
                "tool_calls": [],
                "confidence": 0.9,
                "why": "send generated image",
            },
            {"thought": "图片已经发出，先停一下。", "decision": "sleep", "reply_text": "", "tool_calls": [], "confidence": 0.85, "why": "done"},
        ],
        soft=2,
        hard=2,
    )
    runtime.config.qq_napcat_enabled = True
    runtime.config.qq_napcat_dry_run = True
    runtime.config.qq_napcat_min_send_interval_ms = 0

    def on_reply(reply):
        return runtime.send_adapter_reply(
            reply.get("reply_target") or {},
            str(reply.get("text") or ""),
            reply_id=str(reply.get("id") or ""),
            attachments=reply.get("attachments") if isinstance(reply.get("attachments"), list) else None,
            action_type=str(reply.get("action_type") or "reply"),
        )

    result = runtime.send_message(
        {
            "text": "发图给我",
            "source": "napcat_qq",
            "reply_target": {"adapter": "napcat_qq", "message_type": "private", "user_id": "200020002", "conversation_id": "private:200020002"},
        },
        on_reply=on_reply,
    )

    assert result["replies"][0]["action_type"] == "send_image"
    assert result["replies"][0]["attachments"][0]["file"] == str(image_path)
    message = result["adapter_replies"][0]["body_preview"]["message"]
    assert any(row.get("type") == "text" and "整好了" in row.get("data", {}).get("text", "") for row in message)
    assert any(row.get("type") == "image" and row.get("data", {}).get("file") == str(image_path.resolve()) for row in message)

