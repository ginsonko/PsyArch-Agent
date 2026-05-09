# -*- coding: utf-8 -*-
"""
AP 占位接口 — 先天脚本编码模块（IESM）
=========================================
后续 IESM 正式实现时，替换内部逻辑，接口名和参数不变。

接口列表:
  - check_state_window(packet) → 检查状态变化窗口是否触发先天脚本
  - get_active_scripts()       → 获取当前活跃脚本列表
"""


def _placeholder_result(interface: str, trace_id: str = "") -> dict:
    return {
        "success": True,
        "code": "OK_PLACEHOLDER",
        "message": "占位接口返回成功 / Placeholder interface succeeded",
        "data": {"mock_result_type": "typical_response", "triggered_scripts": []},
        "error": None,
        "meta": {"module": "placeholder_innate_script_api", "interface": interface, "trace_id": trace_id},
    }


def check_state_window(packet: dict, trace_id: str = "") -> dict:
    """
    接收状态变化窗口抄送包，检查是否有先天脚本被触发。

    参数:
        packet: script_check_packet 结构
        trace_id: 追踪 ID

    返回:
        占位结果，含空的 triggered_scripts 列表
    """
    tid = packet.get("trace_id", trace_id)
    return _placeholder_result("check_state_window", tid)


def get_active_scripts(trace_id: str = "") -> dict:
    """获取当前活跃的先天脚本列表。"""
    return _placeholder_result("get_active_scripts", trace_id)
