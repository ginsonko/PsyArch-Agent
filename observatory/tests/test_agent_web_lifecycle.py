# -*- coding: utf-8 -*-

import threading
import queue
from pathlib import Path

from observatory._web import ObservatoryWebServer


class _WebFakeConfig:
    sleep_mode = "reinforced_agency"
    background_tick_interval_ms = 1200
    background_thought_interval_ticks = 30
    reinforced_agency_interval_ticks = 30
    background_save_interval_ticks = 30
    background_save_interval_ms = 60000
    agency_trigger_window_ticks = 12
    agency_trigger_threshold = 0.92
    agency_teacher_gate_enabled = True
    agency_teacher_gate_confidence = 0.62
    wake_drive_threshold = 0.68


class _WebFakeRuntime:
    def __init__(self):
        self.config = _WebFakeConfig()
        self.config.group_continuity_gate_min_confidence = 0.62
        self.bridge_lock_owned = None
        self.saved = False
        self.adapter_logs = []
        self.events = []
        self.sent_replies = []
        self.visible_adapter_messages = []
        self.clear_calls = []
        self.pending_external_inputs = []
        self.group_history = []
        self.continuity_gate_payload = {"should_pass": True, "confidence": 0.91, "addressed_to_bot": True, "needs_reply": True, "reason": "测试门控通过"}
        self.continuity_windows = {}
        self.idle_memory_calls = []

    def set_app_lock(self, lock):
        self.app_lock = lock

    def _bridge_tick_side_effects(self, report, **kwargs):
        self.bridge_lock_owned = kwargs.get("_lock_owned_probe", False)
        progress = kwargs.get("internal_think_progress")
        if callable(progress) and kwargs.get("allow_internal_think"):
            progress({"stage": "waiting_llm", "stage_label": "后台等待 LLM", "decision": "sleep"})
        return {"bridges": [], "bridge_reports": [], "tool_results": [], "teacher_feedback": [], "internal_think_result": None}

    def build_prompt_packet(self, *, reports=None):
        return {"tick_counter": 1, "summary": {}, "action": {"top_actions": []}, "cognitive_feelings": []}

    def _estimate_wake_drive(self, packet):
        return {"wake_drive": 0.0}

    def _remember_snapshot(self, packet):
        return None

    def save(self):
        self.saved = True

    def maybe_run_idle_memory_maintenance(self, *, source="", should_abort=None, force=False):
        aborted = bool(should_abort()) if callable(should_abort) else False
        row = {"source": source, "force": force, "aborted": aborted}
        self.idle_memory_calls.append(row)
        if aborted:
            return {"ran": False, "aborted": True, "reason": "aborted"}
        return {"ran": True, "aborted": False, "wall_ms": 7, "trimmed": {"projection_fatigue_trimmed": 3}}

    def _compact_report_meta(self, report):
        return {"tick": report.get("tick_counter", 0)}

    def _normalize_adapter_event(self, event):
        sender = event.get("sender") or {}
        user_id = str(event.get("user_id") or sender.get("user_id") or "")
        group_id = str(event.get("group_id") or "")
        text = event.get("raw_message") or ""
        mentions = []
        for segment in event.get("message") or []:
            if isinstance(segment, dict) and segment.get("type") == "text":
                text = (segment.get("data") or {}).get("text") or text
            if isinstance(segment, dict) and segment.get("type") == "at":
                qq = str((segment.get("data") or {}).get("qq") or "")
                if qq:
                    mentions.append(qq.lower())
        label_name = sender.get("nickname") or sender.get("card") or ""
        message_type = str(event.get("message_type") or ("group" if group_id else "private"))
        if message_type == "group":
            target_label = event.get("target_label") or f"群聊 {group_id or '-'} / {label_name or user_id or '-'}"
            conversation_id = f"group:{group_id}"
        else:
            target_label = f"私聊 {label_name} ({user_id})" if label_name and user_id else f"私聊 {user_id or '-'}"
            conversation_id = f"private:{user_id}"
        return {
            "adapter": "napcat_qq",
            "message_type": message_type,
            "conversation_id": conversation_id,
            "target_label": target_label,
            "user_id": user_id,
            "group_id": group_id,
            "message_id": str(event.get("message_id") or "m1"),
            "text": text,
            "attachments": [],
            "mentions": mentions,
            "sender": {"user_id": user_id, "nickname": label_name, "card": "", "role": ""},
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": message_type,
                "conversation_id": conversation_id,
                "user_id": user_id,
                "group_id": group_id,
                "target_label": target_label,
            },
        }

    def should_wake(self, normalized):
        if normalized.get("message_type") == "group" and normalized.get("conversation_id") in self.continuity_windows and "@pa" not in str(normalized.get("text", "")).lower():
            return {"should_wake": False, "continuity_gate": True, "reason": "group_continuity_window", "access": {"allowed": True, "reason": "user_whitelist"}}
        return {"should_wake": True, "reason": "private_message", "access": {"allowed": True, "reason": "user_whitelist"}}

    def record_adapter_log(self, row):
        self.adapter_logs.append(dict(row))
        return row

    def record_event(self, row):
        self.events.append(dict(row))
        return row

    def _adapter_message_payload(self, normalized):
        return {
            "text": normalized.get("text", ""),
            "source": normalized.get("adapter") or "adapter",
            "attachments": [],
            "adapter_event": normalized,
            "reply_target": normalized.get("reply_target"),
            "conversation_id": normalized.get("conversation_id"),
            "adapter_label": normalized.get("target_label"),
            "_message_id": normalized.get("message_id"),
        }

    def _remember_adapter_group_history(self, normalized, *, gate_stage=""):
        if normalized.get("message_type") == "group":
            row = {"conversation_id": normalized.get("conversation_id"), "text": normalized.get("text", ""), "gate_stage": gate_stage}
            self.group_history.append(row)
            return row
        return {}

    def _append_visible_adapter_message(self, normalized, *, source="napcat_qq"):
        row = {
            "id": f"{source}:{normalized.get('conversation_id')}:{normalized.get('message_id')}",
            "turn_id": "",
            "role": "user",
            "text": normalized.get("text", ""),
            "source": source,
            "conversation_id": normalized.get("conversation_id", ""),
            "reply_target": normalized.get("reply_target") or {},
            "adapter_event": normalized,
            "adapter_label": normalized.get("target_label", ""),
            "attachments": [],
            "created_at_ms": 100,
        }
        self.visible_adapter_messages.append(row)
        return row

    def _compact_reply_target(self, target):
        return dict(target or {})

    def _normalize_mentions(self, mentions):
        return list(mentions or [])

    def _group_continuity_gate(self, normalized):
        return dict(self.continuity_gate_payload)

    def _consume_group_continuity_gate_result(self, normalized, gate):
        conversation_id = normalized.get("conversation_id") or ""
        passed = bool(gate.get("should_pass")) and float(gate.get("confidence", 0) or 0) >= float(self.config.group_continuity_gate_min_confidence)
        row = self.continuity_windows.get(conversation_id, {"conversation_id": conversation_id, "remaining": 2, "limit": 2})
        if passed:
            row = {**row, "remaining": row.get("limit", 2), "last_gate_result": gate}
            self.continuity_windows[conversation_id] = row
        else:
            remaining = max(0, int(row.get("remaining", 0) or 0) - 1)
            row = {**row, "remaining": remaining, "last_gate_result": gate}
            if remaining:
                self.continuity_windows[conversation_id] = row
            else:
                self.continuity_windows.pop(conversation_id, None)
        return dict(row)

    def _activate_group_continuity_window(self, normalized, *, reason="", gate_result=None):
        if normalized.get("message_type") != "group":
            return {}
        conversation_id = normalized.get("conversation_id") or ""
        row = {"conversation_id": conversation_id, "remaining": 2, "limit": 2, "last_trigger_reason": reason}
        if gate_result:
            row["last_gate_result"] = dict(gate_result)
        self.continuity_windows[conversation_id] = row
        return dict(row)

    def clear_history(self, *, clear_ap_runtime=False):
        self.clear_calls.append({"clear_ap_runtime": clear_ap_runtime})
        return {"ok": True, "clear_ap_runtime": clear_ap_runtime}

    def enqueue_external_input(self, payload):
        row = {
            "id": str(payload.get("id") or payload.get("_message_id") or f"ext_{len(self.pending_external_inputs) + 1}"),
            "turn_id": "",
            "role": payload.get("role") or "user",
            "text": payload.get("text", ""),
            "source": payload.get("source", "user"),
            "conversation_id": payload.get("conversation_id", ""),
            "reply_target": payload.get("reply_target") or {},
            "adapter_event": payload.get("adapter_event") or {},
            "adapter_label": payload.get("adapter_label", ""),
            "attachments": payload.get("attachments") or [],
            "created_at_ms": 101 + len(self.pending_external_inputs),
        }
        self.pending_external_inputs.append(row)
        return row

    def pending_external_input_count(self):
        return len(self.pending_external_inputs)

    def _scheduled_task_origin_from_context(self, context):
        context = context if isinstance(context, dict) else {}
        reply_target = dict(context.get("reply_target") or {})
        adapter_event = dict(context.get("adapter_event") or {})
        return {
            "source": context.get("source") or reply_target.get("adapter") or adapter_event.get("adapter") or "",
            "conversation_id": context.get("conversation_id") or reply_target.get("conversation_id") or adapter_event.get("conversation_id") or "",
            "adapter_label": context.get("adapter_label") or reply_target.get("target_label") or adapter_event.get("target_label") or "",
            "reply_target": reply_target,
            "adapter_event": adapter_event,
        }

    def send_message(self, payload, progress=None, should_stop=None):
        if progress:
            progress({"stage": "waiting_llm", "stage_label": "等待 LLM 1", "decision": "reply"})
        reply = {
            "id": "reply_1",
            "role": "assistant",
            "text": "在呀，银子。",
            "reply_target": payload.get("reply_target") or {},
            "adapter_label": payload.get("adapter_label") or "",
            "conversation_id": payload.get("conversation_id") or "",
            "created_at_ms": 123,
        }
        return {
            "turn": {"id": "turn_1", "decision": "sleep", "ap_tick_count": 1},
            "thoughts": [],
            "replies": [reply],
            "bridges": [],
            "bridge_teacher_feedback": [],
            "ap_packet": {},
            "ap_reports": [],
        }

    def send_adapter_reply(self, event, reply_text):
        row = {"ok": True, "dry_run": False, "event": dict(event), "text": reply_text}
        self.sent_replies.append(row)
        return row

    def _compact_thoughts(self, rows):
        return list(rows or [])

    def _compact_messages(self, rows):
        return list(rows or [])

    def _compact_packet_for_status(self, packet):
        return dict(packet or {})

    def _compact_status(self):
        return {"session": {}}

    def status(self, *, compact=False):
        return {"ok": True}


class _WebFakeApp:
    def __init__(self):
        self.run_count = 0
        self._config = {}
        self._config_override = {}

    def run_cycle(self, text=None, labels=None):
        self.run_count += 1
        return {"tick_counter": self.run_count, "tick_labels": dict(labels or {}), "action": {"executed_actions": []}}


def _server_without_init():
    server = object.__new__(ObservatoryWebServer)
    server.app = _WebFakeApp()
    server.app_lock = threading.RLock()
    runtime = _WebFakeRuntime()
    runtime.set_app_lock(server.app_lock)
    server.agent_runtime = runtime
    server.agent_background_lock = threading.RLock()
    server.agent_background_stop = threading.Event()
    server.agent_background_thread = None
    server.agent_background_state = {
        "running": True,
        "started_at_ms": 0,
        "stopped_at_ms": 0,
        "step_count": 0,
        "trigger_count": 0,
        "thought_check_count": 0,
        "last_save_at_ms": 0,
        "last_save_step_count": 0,
        "last_save_wall_ms": 0,
        "last_step_at_ms": 0,
        "last_result": None,
        "last_error": "",
        "last_idle_memory_maintenance_at_ms": 0,
        "last_idle_memory_maintenance_wall_ms": 0,
        "last_idle_memory_maintenance_result": {},
    }
    server.agent_turn_jobs = {}
    server.agent_turn_jobs_lock = threading.RLock()
    server.agent_turn_job_queue = queue.Queue()
    server.agent_turn_job_stop = threading.Event()
    server.agent_turn_worker = None
    server.group_continuity_gate_jobs = {}
    server.group_continuity_gate_jobs_lock = threading.RLock()
    server.group_continuity_gate_queue = queue.Queue()
    server.group_continuity_gate_stop = threading.Event()
    server.group_continuity_gate_worker = None
    server.agent_foreground_priority = threading.Event()
    server.agent_foreground_priority_lock = threading.RLock()
    server.agent_foreground_priority_until_ms = 0
    server.agent_foreground_priority_reason = ""
    return server


def test_submit_adapter_event_queues_napcat_private_message_for_live_job(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)

    result = server.submit_adapter_event(
        {
            "post_type": "message",
            "message_type": "private",
            "user_id": "200020002",
            "sender": {"nickname": "银子", "user_id": "200020002"},
            "message_id": "qq_1",
            "message": [{"type": "text", "data": {"text": "在嘛?"}}],
        }
    )

    assert result["handled"] is True
    assert result["queued"] is True
    assert result["job"]["status"] == "queued"
    assert result["job"]["user_message"]["adapter_label"] == "私聊 银子 (200020002)"
    assert result["event"]["reply_target"]["user_id"] == "200020002"
    assert any(row.get("event") == "adapter_message_wake" for row in server.agent_runtime.adapter_logs)
    assert server.agent_runtime.visible_adapter_messages[-1]["text"] == "在嘛?"
    assert result["job"]["visible_user_messages"][0]["source"] == "napcat_qq"
    assert result["job"]["payload"] is None
    queued_job = server.agent_turn_jobs[result["job"]["job_id"]]
    assert queued_job["payload"]["_skip_user_message_append"] is True
    assert queued_job["payload"]["_visible_user_message"]["text"] == "在嘛?"


def test_submit_adapter_event_queues_group_continuity_gate_asynchronously(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)
    monkeypatch.setattr(server, "_ensure_group_continuity_gate_worker", lambda: None)
    server.agent_runtime.continuity_windows["group:100010001"] = {"conversation_id": "group:100010001", "remaining": 2, "limit": 2}

    result = server.submit_adapter_event(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": "100010001",
            "user_id": "200020002",
            "sender": {"card": "银子", "user_id": "200020002"},
            "message_id": "g_1",
            "message": [{"type": "text", "data": {"text": "刚才那个呢"}}],
        }
    )

    assert result["handled"] is True
    assert result["queued"] is True
    assert result["continuity_gate"] is True
    assert not server.agent_turn_jobs
    assert server.group_continuity_gate_queue.get_nowait() == result["gate_job"]["job_id"]
    assert server.agent_runtime.group_history[-1]["text"] == "刚才那个呢"
    assert any(row.get("event") == "adapter_message_group_continuity_gate_queued" for row in server.agent_runtime.adapter_logs)


def test_group_continuity_gate_worker_pass_queues_main_turn(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)
    monkeypatch.setattr(server, "_ensure_group_continuity_gate_worker", lambda: None)
    server.agent_runtime.continuity_windows["group:100010001"] = {"conversation_id": "group:100010001", "remaining": 2, "limit": 2}
    queued = server.submit_adapter_event(
        {
            "post_type": "message",
            "message_type": "group",
            "group_id": "100010001",
            "user_id": "200020002",
            "sender": {"card": "银子", "user_id": "200020002"},
            "message_id": "g_2",
            "message": [{"type": "text", "data": {"text": "这个也帮我看看"}}],
        }
    )
    job_id = queued["gate_job"]["job_id"]

    worker = threading.Thread(target=server._group_continuity_gate_worker_loop)
    worker.start()
    deadline = threading.Event()
    for _ in range(100):
        if server.group_continuity_gate_jobs[job_id].get("status") == "passed":
            break
        deadline.wait(0.01)
    server.group_continuity_gate_stop.set()
    server.group_continuity_gate_queue.put("")
    worker.join(timeout=1)

    assert server.group_continuity_gate_jobs[job_id]["status"] == "passed"
    assert server.agent_turn_jobs
    job = next(iter(server.agent_turn_jobs.values()))
    assert job["status"] == "queued"
    assert job["payload"]["_group_continuity_gate"]["should_pass"] is True
    assert job["payload"]["adapter_event"]["conversation_id"] == "group:100010001"
    assert server.agent_runtime.visible_adapter_messages[-1]["text"] == "这个也帮我看看"


def test_submit_agent_turn_does_not_absorb_into_decision_ready_job(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)
    server.agent_turn_jobs["old"] = {
        "job_id": "old",
        "status": "running",
        "stage": "decision_ready",
        "stage_label": "决策已确定：sleep",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "payload": {"text": "旧消息"},
        "user_message": {"id": "old_msg", "role": "user", "text": "旧消息"},
        "initial_user_message": {"id": "old_msg", "role": "user", "text": "旧消息"},
        "visible_user_messages": [{"id": "old_msg", "role": "user", "text": "旧消息"}],
    }

    result = server.submit_agent_turn({"text": "这个临界点的新消息不能丢", "source": "user"})

    assert result["job"]["status"] == "queued"
    assert result["job"]["job_id"] != "old"
    assert result["job"]["user_message"]["text"] == "这个临界点的新消息不能丢"
    assert server.agent_turn_jobs["old"].get("absorbed_messages") in (None, [])
    assert server.agent_runtime.pending_external_input_count() == 0


def test_submit_agent_turn_initial_stage_is_not_app_lock_wait(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)

    result = server.submit_agent_turn({"text": "先排队", "source": "user"})

    assert result["job"]["status"] == "queued"
    assert result["job"]["stage"] == "queued"
    assert "主锁" not in result["job"]["stage_label"]


def test_scheduled_task_payload_preserves_napcat_private_target(monkeypatch):
    server = _server_without_init()
    task = {
        "id": "sleep_1",
        "summary": "提醒测试用户睡觉",
        "prompt": "提醒测试用户该睡觉了",
        "origin": {
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
        },
    }

    payload = server._scheduled_task_turn_payload(task, now_ms=1_800_000_000_000)

    assert payload["text"] == "[闹钟]: 提醒测试用户该睡觉了"
    assert payload["source"] == "napcat_qq"
    assert payload["conversation_id"] == "private:1000010001"
    assert payload["reply_target"]["user_id"] == "1000010001"
    assert payload["adapter_event"]["adapter"] == "napcat_qq"
    assert payload["_visible_user_message"]["source"] == "napcat_qq"


def test_submit_agent_turn_absorbs_into_waiting_llm_job(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)
    server.agent_turn_jobs["old"] = {
        "job_id": "old",
        "status": "running",
        "stage": "waiting_llm",
        "stage_label": "等待 LLM",
        "created_at_ms": 1,
        "started_at_ms": 1,
        "updated_at_ms": 1,
        "payload": {"text": "旧消息"},
        "user_message": {"id": "old_msg", "role": "user", "text": "旧消息"},
        "initial_user_message": {"id": "old_msg", "role": "user", "text": "旧消息"},
        "visible_user_messages": [{"id": "old_msg", "role": "user", "text": "旧消息"}],
    }

    result = server.submit_agent_turn({"text": "等待 LLM 时的新消息", "source": "user"})

    assert result["job"]["job_id"] == "old"
    assert result["job"]["stage"] == "external_input_absorbed"
    assert result["job"]["visible_user_messages"][-1]["text"] == "等待 LLM 时的新消息"
    assert server.agent_runtime.pending_external_input_count() == 1


def test_agent_clear_hides_recent_turn_jobs_and_cancels_active(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    server.agent_turn_jobs["live"] = {
        "job_id": "live",
        "status": "running",
        "stage": "waiting_llm",
        "stage_label": "等待 LLM",
        "created_at_ms": 1,
        "updated_at_ms": 1,
        "user_message": {"role": "user", "text": "旧消息"},
        "reply_message": {"role": "assistant", "text": "旧回复"},
    }
    server.agent_turn_jobs["done"] = {
        "job_id": "done",
        "status": "completed",
        "stage": "completed",
        "created_at_ms": 2,
        "updated_at_ms": 2,
        "reply_message": {"role": "assistant", "text": "完成过的旧回复"},
    }

    result = server.clear_agent_history(clear_ap_runtime=False)
    snapshot = server.agent_turn_jobs_snapshot(limit=10)

    assert result["ok"] is True
    assert result["cleared_turn_jobs"] == 2
    assert result["cancelled_active_jobs"] == 1
    assert server.agent_runtime.clear_calls[-1] == {"clear_ap_runtime": False}
    assert snapshot["jobs"] == []
    assert snapshot["active_jobs"] == []


def test_worker_sends_napcat_reply_to_default_reply_target(monkeypatch):
    server = _server_without_init()
    server.agent_runtime.config.qq_napcat_enabled = True
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)

    queued = server.submit_agent_turn(
        {
            "text": "在嘛?",
            "source": "napcat_qq",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
            "adapter_event": {
                "adapter": "napcat_qq",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
            },
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
            },
        }
    )
    job_id = queued["job"]["job_id"]
    worker = threading.Thread(target=server._agent_turn_worker_loop)
    worker.start()
    deadline = threading.Event()
    for _ in range(100):
        if server.agent_turn_jobs[job_id].get("status") == "completed":
            break
        deadline.wait(0.01)
    server.agent_turn_job_stop.set()
    worker.join(timeout=1)

    job = server.agent_turn_jobs[job_id]
    assert job["status"] == "completed"
    assert server.agent_runtime.sent_replies
    assert server.agent_runtime.sent_replies[0]["event"]["user_id"] == "200020002"
    assert server.agent_runtime.sent_replies[0]["text"] == "在呀，银子。"
    assert job["adapter_replies"][0]["ok"] is True
    dispatch_logs = [row for row in server.agent_runtime.adapter_logs if row.get("event") == "adapter_message_reply_dispatched"]
    assert dispatch_logs
    assert dispatch_logs[-1]["outbound"] is True
    assert dispatch_logs[-1]["outbound_count"] == 1
    assert dispatch_logs[-1]["reply_text"] == "在呀，银子。"
    public = server.agent_turn_jobs_snapshot(job_id=job_id)["job"]
    assert public["reply_messages"][0]["text"] == "在呀，银子。"


def test_worker_records_napcat_outbound_result_when_live_send_disabled(monkeypatch):
    server = _server_without_init()
    server.agent_runtime.config.qq_napcat_enabled = False
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)

    def fake_send_adapter_reply(event, reply_text):
        row = {"ok": False, "mode": "disabled", "reason": "napcat_disabled", "event": dict(event), "text": reply_text}
        server.agent_runtime.sent_replies.append(row)
        return row

    server.agent_runtime.send_adapter_reply = fake_send_adapter_reply
    queued = server.submit_agent_turn(
        {
            "text": "在嘛?",
            "source": "napcat_qq",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
            "adapter_event": {
                "adapter": "napcat_qq",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
            },
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
            },
        }
    )
    job_id = queued["job"]["job_id"]
    worker = threading.Thread(target=server._agent_turn_worker_loop)
    worker.start()
    deadline = threading.Event()
    for _ in range(100):
        if server.agent_turn_jobs[job_id].get("status") == "completed":
            break
        deadline.wait(0.01)
    server.agent_turn_job_stop.set()
    worker.join(timeout=1)

    job = server.agent_turn_jobs[job_id]
    assert job["status"] == "completed"
    assert job["adapter_replies"][0]["reason"] == "napcat_disabled"
    assert server.agent_runtime.sent_replies[0]["event"]["user_id"] == "200020002"
    assert any(row.get("event") == "adapter_message_reply_failed" for row in server.agent_runtime.adapter_logs)


def test_worker_skips_queued_job_that_was_stopped_before_start(monkeypatch):
    server = _server_without_init()
    server.agent_runtime.config.qq_napcat_enabled = True
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "_ensure_agent_turn_worker", lambda: None)

    queued = server.submit_agent_turn(
        {
            "text": "在嘛?",
            "source": "napcat_qq",
            "conversation_id": "private:200020002",
            "adapter_label": "私聊 银子 (200020002)",
            "adapter_event": {
                "adapter": "napcat_qq",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
            },
            "reply_target": {
                "adapter": "napcat_qq",
                "message_type": "private",
                "conversation_id": "private:200020002",
                "user_id": "200020002",
                "target_label": "私聊 银子 (200020002)",
            },
        }
    )
    job_id = queued["job"]["job_id"]
    stop_result = server.request_stop_agent_turn(job_id=job_id, reason="unit_stop_before_start")

    assert stop_result["ok"] is True
    assert stop_result["job"]["status"] == "cancelled"

    worker = threading.Thread(target=server._agent_turn_worker_loop)
    worker.start()
    deadline = threading.Event()
    for _ in range(100):
        if server.agent_turn_job_queue.unfinished_tasks == 0:
            break
        deadline.wait(0.01)
    server.agent_turn_job_stop.set()
    worker.join(timeout=1)

    job = server.agent_turn_jobs[job_id]
    assert job["status"] == "cancelled"
    assert job["stage"] == "operator_stopped"
    assert not server.agent_runtime.sent_replies


def test_background_step_uses_existing_runtime_and_releases_lock_before_bridge(monkeypatch):
    server = _server_without_init()
    original_bridge = server.agent_runtime._bridge_tick_side_effects

    def bridge_probe(report, **kwargs):
        is_owned = getattr(server.app_lock, "_is_owned", lambda: False)
        kwargs["_lock_owned_probe"] = bool(is_owned())
        return original_bridge(report, **kwargs)

    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    server.agent_runtime._bridge_tick_side_effects = bridge_probe

    result = server._agent_background_step()

    assert result["ok"] is True
    assert server.app.run_count == 1
    assert server.agent_runtime.bridge_lock_owned is False
    assert server.agent_runtime.saved is False
    assert result["background_save"]["saved"] is False


def test_background_lock_busy_is_transient_and_not_reported_as_waiting(monkeypatch):
    server = _server_without_init()
    lock_acquired = threading.Event()
    release_lock = threading.Event()

    def hold_lock():
        with server.app_lock:
            lock_acquired.set()
            release_lock.wait(timeout=2)

    holder = threading.Thread(target=hold_lock)
    holder.start()
    assert lock_acquired.wait(timeout=1)
    try:
        result = server._agent_background_step()
    finally:
        release_lock.set()
        holder.join(timeout=2)

    assert result["stage"] == "background_skipped_app_lock_busy"
    assert result["transient"] is True
    assert "等待 AP 主锁" not in result["stage_label"]


def test_background_step_saves_on_configured_interval(monkeypatch):
    server = _server_without_init()
    server.agent_runtime.config.background_save_interval_ticks = 1
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})

    result = server._agent_background_step()

    assert result["ok"] is True
    assert result["background_save"]["saved"] is True
    assert result["background_save"]["reason"] == "tick_interval"
    assert server.agent_runtime.saved is True


def test_foreground_priority_pauses_background_before_tick(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})

    server._mark_agent_foreground_pending("unit_test", hold_ms=10_000)
    result = server._agent_background_step()

    assert result["reason"] == "background_paused_for_foreground_turn"
    assert result["foreground_priority"] is True
    assert server.app.run_count == 0


def test_background_step_runs_idle_memory_maintenance_when_quiet(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})

    result = server._agent_background_step()

    assert result["ok"] is True
    assert result["triggered"] is False
    assert result["idle_memory_maintenance"]["ran"] is True
    assert server.agent_runtime.idle_memory_calls
    assert server.agent_background_state["last_idle_memory_maintenance_wall_ms"] == 7


def test_background_status_keeps_compact_thought_result(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})
    monkeypatch.setattr(server, "app_lock_status", lambda: {"locked": False})
    monkeypatch.setattr(
        server.agent_runtime,
        "status_compact_cached",
        lambda: {"ap_packet": {"tick_counter": 3, "generated_at_ms": 123}},
        raising=False,
    )
    monkeypatch.setattr(
        server.agent_runtime,
        "_compact_thoughts",
        lambda rows: [{"id": "thought_1", "text": "后台想法", "why": "测试", "created_at_ms": 123}] if rows else [],
        raising=False,
    )
    monkeypatch.setattr(
        server.agent_runtime,
        "_compact_messages",
        lambda rows: [{"id": "reply_1", "text": "后台回复", "created_at_ms": 124}] if rows else [],
        raising=False,
    )
    monkeypatch.setattr(
        server.agent_runtime,
        "_compact_turns",
        lambda rows: [{"id": "turn_1", "decision": "reply", "created_at_ms": 125}] if rows else [],
        raising=False,
    )
    server.agent_background_state["last_result"] = {
        "stage": "background_internal_think",
        "stage_label": "后台内部思考已触发",
        "ap_packet": {"tick_counter": 2},
        "thought_result": {
            "turn": {"id": "turn_1", "decision": "reply"},
            "thoughts": [{"id": "thought_1", "text": "后台想法"}],
            "replies": [{"id": "reply_1", "text": "后台回复"}],
        },
    }

    status = server.agent_background_status()

    thought_result = status["last_result"]["thought_result"]
    assert thought_result["decision"] == "reply"
    assert thought_result["thoughts"][0]["text"] == "后台想法"
    assert thought_result["replies"][0]["text"] == "后台回复"


def test_background_step_skips_idle_memory_maintenance_when_foreground_pending(monkeypatch):
    server = _server_without_init()
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})

    server._mark_agent_foreground_pending("unit_test", hold_ms=10_000)
    result = server._agent_background_step()

    assert result["reason"] == "background_paused_for_foreground_turn"
    assert not server.agent_runtime.idle_memory_calls


def test_reinforced_background_step_always_runs_internal_think_on_interval(monkeypatch):
    server = _server_without_init()
    server.agent_runtime.config.sleep_mode = "reinforced_agency"
    server.agent_runtime.config.reinforced_agency_interval_ticks = 5
    server.agent_background_state["step_count"] = 4
    monkeypatch.setattr("observatory._web.apply_experiment_default_app_overrides", lambda app, source: {})

    seen: dict[str, object] = {}

    def fake_gate(*, packet, drive, mode):
        return {"should_wake": False, "confidence": 0.01, "reason": "teacher_gate_reject_for_test", "mode": mode}

    def fake_internal_think(**kwargs):
        seen["kwargs"] = dict(kwargs)
        progress = kwargs.get("progress")
        if callable(progress):
            progress({"stage": "waiting_llm", "stage_label": "后台等待 LLM", "decision": "sleep", "llm_wait_tick_count": 2})
        return {
            "turn": {"id": "turn_bg_1", "decision": "sleep"},
            "thoughts": [{"id": "thought_bg_1", "text": "30 tick 到点后的总结"}],
            "replies": [],
            "decision": "sleep",
        }

    monkeypatch.setattr(server.agent_runtime, "_teacher_gate_should_wake", fake_gate, raising=False)
    monkeypatch.setattr(server.agent_runtime, "_run_internal_think", fake_internal_think, raising=False)

    result = server._agent_background_step()

    assert result["ok"] is True
    assert result["triggered"] is True
    assert result["reason"] == "background_internal_think_sleep"
    assert result["thought_result"]["thoughts"][0]["text"] == "30 tick 到点后的总结"
    assert result["teacher_gate"]["reason"] == "teacher_gate_reject_for_test"
    assert result["teacher_gate"]["periodic_eval_due"] is True
    assert result["teacher_gate"]["trigger_policy"] == "observability_only"
    assert seen["kwargs"]["reason"] == "reinforced_periodic_internal_think"
    assert seen["kwargs"]["run_ap_while_waiting_llm"] is None


def test_stop_requested_job_keeps_stable_stopping_stage():
    server = _server_without_init()
    job_id = "agent_job_stop_probe"
    now = 12345
    server.agent_turn_jobs[job_id] = {
        "job_id": job_id,
        "status": "running",
        "stage": "stopping",
        "stage_label": "正在停止思考",
        "created_at_ms": now,
        "updated_at_ms": now,
        "cancel_requested": True,
    }

    server._update_agent_turn_job(
        job_id,
        {
            "status": "running",
            "stage": "waiting_llm_ap_tick",
            "stage_label": "等待 LLM，AP 空 tick 1",
            "llm_wait_tick_count": 1,
        },
    )

    job = server.agent_turn_jobs[job_id]
    assert job["stage"] == "stopping"
    assert job["stage_label"] == "正在停止思考"
    assert job["llm_wait_tick_count"] == 1

    server._update_agent_turn_job(
        job_id,
        {
            "status": "running",
            "stage": "operator_stopped",
            "stage_label": "已手动停止，进入休眠",
        },
    )

    job = server.agent_turn_jobs[job_id]
    assert job["stage"] == "operator_stopped"
    assert job["stage_label"] == "已手动停止，进入休眠"


def test_stop_without_active_job_stops_background_and_reports_state():
    server = _server_without_init()
    server.agent_background_state["running"] = True

    result = server.request_stop_agent_turn(reason="unit_stop")

    assert result["ok"] is True
    assert result["reason"] == "background_stop_requested"
    assert result["job"] == {}
    assert result["background"]["running"] is False
    assert server.agent_background_stop.is_set()


def test_background_internal_think_progress_updates_status_panel_state():
    server = _server_without_init()

    server._background_internal_think_progress(
        {
            "stage": "waiting_llm",
            "stage_label": "等待 LLM 1",
            "decision": "reply",
            "current_thought_text": "后台正在判断要不要继续参与。",
            "ap_packet": {"summary": {"total_er": 1.0}},
        }
    )

    status = server.agent_background_status()
    result = status["last_result"]
    assert result["stage_label"] == "等待 LLM 1"
    assert result["decision"] == "reply"
    assert result["internal_think_progress"]["current_thought_text"] == "后台正在判断要不要继续参与。"
    assert status["last_stage_label"] == "等待 LLM 1"


def test_launch_napcat_prefers_shell_loader_and_patches_onebot(tmp_path, monkeypatch):
    repo = tmp_path / "PA"
    obs = repo / "Artificial-PsyArch" / "observatory"
    obs.mkdir(parents=True)
    napcat = repo / "NapCatQQ"
    shell = napcat / "packages" / "napcat-shell-loader"
    shell.mkdir(parents=True)
    launcher = shell / "launcher-win10.bat"
    launcher.write_text("@echo off\n", encoding="utf-8")
    (shell / "napcat.mjs").write_text("export {};\n", encoding="utf-8")
    webui = napcat / "packages" / "napcat-webui-backend" / "webui.json"
    webui.parent.mkdir(parents=True)
    webui.write_text('{"port":6099,"token":"random"}', encoding="utf-8")
    onebot = napcat / "packages" / "napcat-develop" / "config" / "onebot11.json"
    onebot.parent.mkdir(parents=True)
    onebot.write_text('{"network":{"httpServers":[],"httpClients":[]}}', encoding="utf-8")
    fake_web_path = obs / "_web.py"
    fake_web_path.write_text("", encoding="utf-8")
    import observatory._web as web_module

    monkeypatch.setattr(web_module, "__file__", str(fake_web_path))
    launched = {}
    monkeypatch.setattr("observatory._web.webbrowser.open", lambda url: launched.setdefault("url", url))

    def fake_popen(args, cwd=None, creationflags=0):
        launched["args"] = args
        launched["cwd"] = cwd
        launched["creationflags"] = creationflags

        class Proc:
            pass

        return Proc()

    monkeypatch.setattr("observatory._web.subprocess.Popen", fake_popen)
    monkeypatch.setattr("observatory._web.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("observatory._web.socket.create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("closed")))
    server = _server_without_init()
    server.web_host = "127.0.0.1"
    server.web_port = 8765

    result = server.launch_napcat()
    payload = __import__("json").loads(onebot.read_text(encoding="utf-8"))
    client = payload["network"]["httpClients"][0]

    assert result["launcher"].endswith("launcher-win10.bat")
    assert Path(launched["cwd"]).name == "napcat-shell-loader"
    assert result["launch_mode"] == "shell-loader-release"
    assert result["webui_url"] == "http://127.0.0.1:6099/webui/"
    assert launched["url"] == "http://127.0.0.1:6099/webui/"
    assert client["url"] == "http://127.0.0.1:8765/api/agent/napcat/event"
    assert client["messagePostFormat"] == "array"
    assert payload["network"]["httpServers"][0]["port"] == 3000


def test_launch_napcat_source_checkout_uses_pa_start_script_when_shell_loader_main_missing(tmp_path, monkeypatch):
    repo = tmp_path / "PA"
    obs = repo / "Artificial-PsyArch" / "observatory"
    obs.mkdir(parents=True)
    napcat = repo / "NapCatQQ"
    shell = napcat / "packages" / "napcat-shell-loader"
    shell.mkdir(parents=True)
    (shell / "launcher-win10.bat").write_text("@echo off\n", encoding="utf-8")
    develop = napcat / "packages" / "napcat-develop"
    develop.mkdir(parents=True)
    (develop / "loadNapCat.cjs").write_text("console.log('dev');\n", encoding="utf-8")
    onebot = develop / "config" / "onebot11.json"
    onebot.parent.mkdir(parents=True)
    onebot.write_text('{"network":{"httpServers":[],"httpClients":[]}}', encoding="utf-8")
    start_bat = repo / "start-napcat-pa.bat"
    start_bat.write_text("@echo off\n", encoding="utf-8")
    fake_web_path = obs / "_web.py"
    fake_web_path.write_text("", encoding="utf-8")
    import observatory._web as web_module

    monkeypatch.setattr(web_module, "__file__", str(fake_web_path))
    launched = {}
    monkeypatch.setattr("observatory._web.webbrowser.open", lambda url: launched.setdefault("url", url))

    def fake_popen(args, cwd=None, creationflags=0):
        launched["args"] = args
        launched["cwd"] = cwd
        launched["creationflags"] = creationflags

        class Proc:
            pass

        return Proc()

    monkeypatch.setattr("observatory._web.subprocess.Popen", fake_popen)
    monkeypatch.setattr("observatory._web.time.sleep", lambda _seconds: None)
    monkeypatch.setattr("observatory._web.socket.create_connection", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("closed")))
    server = _server_without_init()
    server.web_host = "127.0.0.1"
    server.web_port = 8765

    result = server.launch_napcat()
    payload = __import__("json").loads(onebot.read_text(encoding="utf-8"))

    assert result["launcher"].endswith("start-napcat-pa.bat")
    assert Path(launched["cwd"]) == repo
    assert result["launch_mode"] == "source-dev-prepare"
    assert result["webui_url"] == "http://127.0.0.1:6099/webui/"
    assert launched["url"] == "http://127.0.0.1:6099/webui/"
    assert result["launcher_checks"]["release_ready"] is False
    assert result["launcher_checks"]["source_ready"] is True
    assert result["launcher_checks"]["source_dist_ready"] is False
    assert payload["network"]["httpClients"][0]["url"] == "http://127.0.0.1:8765/api/agent/napcat/event"

