# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 近期变化事件窗口
==================================
维护固定大小的 state_change_event 缓冲区（FIFO），
用于脚本检查抄送和状态回放。
"""


class HistoryWindow:
    """
    近期变化事件窗口。

    使用固定大小列表 + 计数器实现 FIFO，避免频繁内存分配。
    当缓冲区满时，最旧的事件被自动覆盖。
    """

    def __init__(self, config: dict):
        self._max_events = config.get("history_window_max_events", 5000)
        self._events: list[dict] = []
        self._total_recorded: int = 0

    def append(self, event: dict):
        """添加一个事件。"""
        self._events.append(event)
        self._total_recorded += 1
        # 超过容量时裁剪前端
        if len(self._events) > self._max_events:
            # 保留后半部分，避免频繁裁剪
            trim_count = len(self._events) - self._max_events
            self._events = self._events[trim_count:]

    def append_many(self, events: list[dict]):
        """批量添加事件。"""
        valid_events = [ev for ev in (events or []) if isinstance(ev, dict)]
        if not valid_events:
            return
        self._events.extend(valid_events)
        self._total_recorded += len(valid_events)
        if len(self._events) > self._max_events:
            trim_count = len(self._events) - self._max_events
            self._events = self._events[trim_count:]

    def get_recent(self, count: int | None = None) -> list[dict]:
        """获取最近的 N 个事件（None=全部）。"""
        if count is None:
            return list(self._events)
        return list(self._events[-count:])

    def get_events_since(self, since_ms: int) -> list[dict]:
        """获取指定时间戳之后的所有事件。"""
        return [ev for ev in self._events if ev.get("timestamp_ms", 0) >= since_ms]

    @property
    def size(self) -> int:
        return len(self._events)

    @property
    def total_recorded(self) -> int:
        return self._total_recorded

    def clear(self) -> int:
        """清空窗口，返回清除数量。"""
        count = len(self._events)
        self._events.clear()
        return count

    def get_summary(self) -> dict:
        """返回窗口摘要。"""
        return {
            "current_size": self.size,
            "max_size": self._max_events,
            "total_recorded": self._total_recorded,
        }

    def update_config(self, config: dict):
        new_max = config.get("history_window_max_events", self._max_events)
        if new_max != self._max_events:
            self._max_events = new_max
            if len(self._events) > self._max_events:
                trim = len(self._events) - self._max_events
                self._events = self._events[trim:]
