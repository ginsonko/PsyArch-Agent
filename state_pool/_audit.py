# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 高风险操作审计器
==================================
记录 clear_state_pool、强制删除、关键配置修改等高风险操作。
审计日志和 error 日志同级别对待，确保可追溯。
"""

import json
import time
from typing import Any

from ._logger import ModuleLogger


class AuditLogger:
    """
    高风险操作审计器。
    所有审计事件自动写入 error 日志层（最高保存优先级）。
    """

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
    ):
        """
        记录一条审计事件。

        参数:
            trace_id: 调用链追踪 ID
            interface: 触发审计的接口名
            action: 操作描述（如 "clear_state_pool"）
            reason: 操作原因
            operator: 操作者标识（可选）
            tick_id: 认知滴答 ID
            detail: 操作详情
            success: 操作是否成功
        """
        audit_detail = {
            "action": action,
            "reason": reason,
            "operator": operator or "unknown",
            "success": success,
        }
        if detail:
            audit_detail.update(detail)

        self._logger.error(
            trace_id=trace_id,
            interface=interface,
            code="AUDIT_HIGH_RISK",
            message_zh=f"执行高风险操作：{action}（原因：{reason}）",
            message_en=f"High-risk operation executed: {action} (reason: {reason})",
            tick_id=tick_id,
            detail=audit_detail,
        )
