# -*- coding: utf-8 -*-
"""
AP 占位接口 — HDB（全息深度数据库）
=====================================
后续 HDB 正式实现时，仅需替换本文件内部逻辑，接口名和参数不变。

接口列表:
  - query_by_stimulus(stimulus_data) → 按刺激内容查询结构
  - store_structure(structure_data)  → 存储结构
  - store_experience(experience_data) → 存储情景记忆
"""


def _placeholder_result(interface: str, trace_id: str = "") -> dict:
    """所有占位接口的标准返回。"""
    return {
        "success": True,
        "code": "OK_PLACEHOLDER",
        "message": "占位接口返回成功 / Placeholder interface succeeded",
        "data": {"mock_result_type": "typical_response", "items": []},
        "error": None,
        "meta": {"module": "placeholder_hdb_api", "interface": interface, "trace_id": trace_id},
    }


def query_by_stimulus(stimulus_data: dict, trace_id: str = "", top_k: int = 10) -> dict:
    """
    按刺激内容查询 HDB 中已有结构。

    参数:
        stimulus_data: 刺激数据（SA/CSA 格式）
        trace_id: 追踪 ID
        top_k: 返回前 K 个结果
    """
    return _placeholder_result("query_by_stimulus", trace_id)


def store_structure(structure_data: dict, trace_id: str = "") -> dict:
    """存储一个新结构到 HDB。"""
    return _placeholder_result("store_structure", trace_id)


def store_experience(experience_data: dict, trace_id: str = "") -> dict:
    """存储一条情景记忆到 HDB。"""
    return _placeholder_result("store_experience", trace_id)
