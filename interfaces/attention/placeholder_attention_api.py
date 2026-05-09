# -*- coding: utf-8 -*-
"""
AP 占位接口 — 注意力过滤器（AF）
==================================
接口列表:
  - receive_state_snapshot(snapshot)  → 接收状态池快照
  - apply_attention_filter(items, budget) → 执行注意力过滤
"""


def _placeholder_result(interface: str, trace_id: str = "") -> dict:
    return {
        "success": True,
        "code": "OK_PLACEHOLDER",
        "message": "占位接口返回成功 / Placeholder interface succeeded",
        "data": {"mock_result_type": "typical_response", "filtered_item_ids": []},
        "error": None,
        "meta": {"module": "placeholder_attention_api", "interface": interface, "trace_id": trace_id},
    }


def receive_state_snapshot(snapshot: dict, trace_id: str = "") -> dict:
    """接收状态池摘要快照用于注意力过滤。"""
    return _placeholder_result("receive_state_snapshot", trace_id)


def apply_attention_filter(items: list, budget: int = 64, trace_id: str = "") -> dict:
    """对候选对象执行注意力预算过滤。"""
    result = _placeholder_result("apply_attention_filter", trace_id)
    result["data"]["budget"] = budget
    result["data"]["input_count"] = len(items)
    return result
