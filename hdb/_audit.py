# -*- coding: utf-8 -*-
"""
Audit logger for HDB high-risk operations.
"""

from __future__ import annotations

from ._logger import ModuleLogger


class AuditLogger:
    def __init__(self, logger: ModuleLogger):
        self._logger = logger

    def record(
        self,
        trace_id: str,
        interface: str,
        action: str,
        reason: str,
        operator: str = "",
        tick_id: str = "",
        detail: dict | None = None,
        success: bool = True,
    ) -> None:
        payload = {
            "action": action,
            "reason": reason,
            "operator": operator or "unknown",
            "success": success,
        }
        if detail:
            payload.update(detail)
        self._logger.error(
            trace_id=trace_id,
            interface=interface,
            code="AUDIT_HIGH_RISK",
            message_zh=f"执行高风险操作：{action}",
            message_en=f"High-risk operation executed: {action}",
            tick_id=tick_id,
            detail=payload,
        )
