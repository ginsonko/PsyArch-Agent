# -*- coding: utf-8 -*-
"""
AP 占位接口 — 行动模块
========================
接口列表:
  - evaluate_action_candidates(candidates) → 评估行动候选
  - execute_action(action_plan)           → 执行行动
"""


def _placeholder_result(interface: str, trace_id: str = "") -> dict:
    return {
        "success": True,
        "code": "OK_PLACEHOLDER",
        "message": "占位接口返回成功 / Placeholder interface succeeded",
        "data": {"mock_result_type": "typical_response", "selected_action": None},
        "error": None,
        "meta": {"module": "placeholder_action_api", "interface": interface, "trace_id": trace_id},
    }


def evaluate_action_candidates(candidates: list, trace_id: str = "") -> dict:
    """评估行动候选列表。"""
    return _placeholder_result("evaluate_action_candidates", trace_id)


def execute_action(action_plan: dict, trace_id: str = "") -> dict:
    """执行选定的行动。"""
    return _placeholder_result("execute_action", trace_id)
