# -*- coding: utf-8 -*-
"""
AP 占位接口 — 情绪管理器（EMgr）
==================================
接口列表:
  - update_emotion_state(state_data) → 更新情绪状态
  - get_emotion_snapshot()           → 获取情绪快照
"""


def _placeholder_result(interface: str, trace_id: str = "") -> dict:
    return {
        "success": True,
        "code": "OK_PLACEHOLDER",
        "message": "占位接口返回成功 / Placeholder interface succeeded",
        "data": {"mock_result_type": "typical_response",
                 "emotion_channels": {"positive_valence": 0.5, "negative_valence": 0.3}},
        "error": None,
        "meta": {"module": "placeholder_emotion_api", "interface": interface, "trace_id": trace_id},
    }


def update_emotion_state(state_data: dict, trace_id: str = "") -> dict:
    """根据状态池变化更新情绪通道。"""
    return _placeholder_result("update_emotion_state", trace_id)


def get_emotion_snapshot(trace_id: str = "") -> dict:
    """获取当前情绪通道快照。"""
    return _placeholder_result("get_emotion_snapshot", trace_id)
