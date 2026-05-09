# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 合并引擎
==========================
负责将重复对象合并为单一 state_item，避免状态池膨胀。
原型阶段仅支持 ref_object_id 完全匹配的合并；
弱语义合并（allow_weak_semantic_merge）预留但默认关闭。
"""


class MergeEngine:
    """
    合并引擎。

    合并策略:
      - 同一 ref_object_id 的重复输入 → 能量叠加（非新建）
      - merge_only_same_ref_object=true → 仅按 ref_object_id 判断
      - allow_weak_semantic_merge=false → 不做语义级别合并
    """

    def __init__(self, config: dict):
        self._config = config

    def should_merge(self, existing_item: dict, candidate_item: dict) -> bool:
        """
        判断两个 state_item 是否应合并。

        当前规则:
          1. merge_duplicate_items 必须为 true
          2. ref_object_id 必须完全相同
          3. ref_object_type 必须相同
        """
        if not self._config.get("merge_duplicate_items", True):
            return False

        if self._config.get("merge_only_same_ref_object", True):
            same_ref = (
                existing_item.get("ref_object_id") == candidate_item.get("ref_object_id")
                and existing_item.get("ref_object_type") == candidate_item.get("ref_object_type")
            )
            return same_ref

        return False

    def merge_items(self, existing: dict, candidate: dict) -> dict:
        """
        将 candidate 的信息合并到 existing 中。

        合并策略:
          - 能量：叠加 candidate 的 er/ev 到 existing
          - ref_snapshot：保留 existing 的（因为它更完整）
          - lifecycle: 更新 last_active_tick
          - 不直接修改 existing，返回需要 apply 的能量增量信息
        """
        candidate_energy = candidate.get("energy", {})
        delta_er = candidate_energy.get("er", 0.0)
        delta_ev = candidate_energy.get("ev", 0.0)

        return {
            "target_item_id": existing["id"],
            "delta_er": delta_er,
            "delta_ev": delta_ev,
            "merge_source_ref_id": candidate.get("ref_object_id", ""),
            "merge_source_spi_id": candidate.get("id", ""),
        }

    def update_config(self, config: dict):
        self._config = config
