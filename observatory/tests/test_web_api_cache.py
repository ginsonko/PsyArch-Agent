# -*- coding: utf-8 -*-

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from observatory import _web


class _BusyLock:
    def acquire(self, timeout: float | None = None) -> bool:
        return False

    def release(self) -> None:  # pragma: no cover - should never be called
        raise AssertionError("busy lock should not be released")


def test_auto_tuner_state_cache_returns_stale_payload_when_app_lock_is_busy(monkeypatch):
    now_ms = int(time.time() * 1000)
    server = SimpleNamespace(
        app=None,
        app_lock=_BusyLock(),
        auto_tuner_state_lock=threading.RLock(),
        auto_tuner_state_cache={
            "payload": {"state": {"persisted_params": {"demo": 1}}, "summary": {"persisted_param_count": 1}},
            "mode": "live",
            "refreshed_at_ms": now_ms - (_web._AUTO_TUNER_STATE_CACHE_TTL_MS + 5),
        },
    )

    def _unexpected_read(app=None):
        raise AssertionError("stale cached payload should be returned before disk fallback")

    monkeypatch.setattr(_web.exp, "read_auto_tuner_state", _unexpected_read)
    payload = _web._load_auto_tuner_state_cached(server)

    assert payload["state"]["persisted_params"]["demo"] == 1
    assert payload["summary"]["persisted_param_count"] == 1
    assert payload["fetch_meta"]["mode"] == "stale_cache"


def test_auto_tuner_state_cache_falls_back_to_disk_snapshot_without_app_lock(monkeypatch):
    server = SimpleNamespace(
        app=object(),
        app_lock=_BusyLock(),
        auto_tuner_state_lock=threading.RLock(),
        auto_tuner_state_cache={},
    )
    calls: list[object | None] = []

    def _fake_read(app=None):
        calls.append(app)
        return {"state": {"persisted_params": {"demo": 2}}, "summary": {"persisted_param_count": 1}}

    monkeypatch.setattr(_web.exp, "read_auto_tuner_state", _fake_read)
    payload = _web._load_auto_tuner_state_cached(server)

    assert calls == [None]
    assert payload["state"]["persisted_params"]["demo"] == 2
    assert payload["fetch_meta"]["mode"] == "fallback_disk"
