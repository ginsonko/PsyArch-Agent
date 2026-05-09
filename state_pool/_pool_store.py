# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 主存储与索引
==============================
维护 state_item 的主存储字典和辅助索引。
支持按 id、ref_object_id、ref_object_type 快速查找，
以及容量管理和溢出淘汰。
"""

import heapq
from typing import Any


class PoolStore:
    """
    状态池主存储。

    内部结构:
      _items: dict[spi_id -> state_item]         主存储
      _ref_index: dict[ref_obj_id -> spi_id]     引用对象ID → 池项ID 索引
      _root_structure_index: dict[root_st_id -> spi_id] 运行态根结构ID → 池项ID 索引
      _semantic_index: dict[signature -> spi_id] 语义签名 → 池项ID 索引
      _semantic_context_index: dict[key -> spi_id] 语义+上下文 → 池项ID 索引
      _type_index: dict[ref_obj_type -> set[spi_id]]  按对象类型分类索引
    """

    def __init__(self, config: dict):
        self._config = config
        self._items: dict[str, dict] = {}
        self._ref_index: dict[str, str] = {}
        self._root_structure_index: dict[str, str] = {}
        self._semantic_index: dict[str, str] = {}
        self._semantic_context_index: dict[str, str] = {}
        self._type_index: dict[str, set[str]] = {}

    # ================================================================== #
    #                       基础操作                                       #
    # ================================================================== #

    @property
    def size(self) -> int:
        """当前池内对象数量。"""
        return len(self._items)

    @property
    def max_items(self) -> int:
        return self._config.get("pool_max_items", 5000)

    def get(self, spi_id: str) -> dict | None:
        """按 state_item ID 查找。"""
        return self._items.get(spi_id)

    def get_by_ref(self, ref_object_id: str) -> dict | None:
        """按引用对象 ID 查找。"""
        spi_id = self._ref_index.get(ref_object_id)
        if spi_id:
            return self._items.get(spi_id)
        return None

    def get_by_root_structure_id(self, root_structure_id: str) -> dict | None:
        """按运行态根结构 ID 查找。"""
        spi_id = self._root_structure_index.get(str(root_structure_id or ""))
        if spi_id:
            return self._items.get(spi_id)
        return None

    def get_by_semantic_signature(self, semantic_signature: str) -> dict | None:
        """按语义签名查找。"""
        spi_id = self._semantic_index.get(semantic_signature)
        if spi_id:
            return self._items.get(spi_id)
        return None

    def get_by_semantic_context_key(self, semantic_context_key: str) -> dict | None:
        """按语义+上下文身份查找。"""
        spi_id = self._semantic_context_index.get(semantic_context_key)
        if spi_id:
            return self._items.get(spi_id)
        return None

    def get_by_type(self, ref_object_type: str) -> list[dict]:
        """按引用对象类型查找所有匹配项。"""
        spi_ids = self._type_index.get(ref_object_type, set())
        return [self._items[sid] for sid in spi_ids if sid in self._items]

    def get_all(self) -> list[dict]:
        """返回所有活跃对象列表。"""
        return list(self._items.values())

    def contains_ref(self, ref_object_id: str) -> bool:
        """检查是否已有该引用对象。"""
        return ref_object_id in self._ref_index

    # ================================================================== #
    #                       写入操作                                       #
    # ================================================================== #

    def insert(self, item: dict) -> bool:
        """
        插入一个新的 state_item。

        返回:
            True 表示成功插入，False 表示容量已满且淘汰策略拒绝。
        """
        spi_id = item["id"]
        ref_id = item.get("ref_object_id", "")
        ref_type = item.get("ref_object_type", "")

        # 容量检查
        if self.size >= self.max_items:
            strategy = self._config.get("pool_overflow_strategy", "prune_lowest_then_reject")
            if strategy == "reject_new":
                return False
            elif strategy in ("prune_lowest_then_reject", "prune_lowest_then_insert"):
                # 淘汰最低能量对象腾出空间
                pruned = self._prune_lowest_energy(count=1)
                if not pruned and strategy == "prune_lowest_then_reject":
                    return False

        # 写入主存储
        self._items[spi_id] = item

        # 更新引用索引
        alias_ids = item.get("ref_alias_ids") or ([ref_id] if ref_id else [])
        for alias_id in alias_ids:
            if alias_id:
                self._ref_index[alias_id] = spi_id

        root_structure_id = self._extract_root_structure_id(item)
        if root_structure_id:
            self._root_structure_index[root_structure_id] = spi_id

        semantic_signature = item.get("semantic_signature", "")
        if semantic_signature:
            self._semantic_index[semantic_signature] = spi_id
        semantic_context_key = item.get("semantic_context_key", "")
        if semantic_context_key:
            self._semantic_context_index[semantic_context_key] = spi_id
        ref_type = item.get("ref_object_type", "")
        if ref_type:
            self._type_index.setdefault(ref_type, set()).add(spi_id)

        # 更新类型索引
        if ref_type:
            if ref_type not in self._type_index:
                self._type_index[ref_type] = set()
            self._type_index[ref_type].add(spi_id)

        return True

    def update(self, spi_id: str, item: dict):
        """原地更新一个已有对象。"""
        self._items[spi_id] = item
        self.reindex_item(spi_id)

    def reindex_item(self, spi_id: str) -> None:
        """Refresh secondary indexes for a mutated in-place item."""
        item = self._items.get(spi_id)
        if not item:
            return
        self._remove_index_entries_for_spi(spi_id)
        ref_id = item.get("ref_object_id", "")
        alias_ids = item.get("ref_alias_ids") or ([ref_id] if ref_id else [])
        for alias_id in alias_ids:
            if alias_id:
                self._ref_index[alias_id] = spi_id
        root_structure_id = self._extract_root_structure_id(item)
        if root_structure_id:
            self._root_structure_index[root_structure_id] = spi_id
        semantic_signature = item.get("semantic_signature", "")
        if semantic_signature:
            self._semantic_index[semantic_signature] = spi_id
        semantic_context_key = item.get("semantic_context_key", "")
        if semantic_context_key:
            self._semantic_context_index[semantic_context_key] = spi_id

    def remove(self, spi_id: str) -> dict | None:
        """移除并返回一个对象。"""
        item = self._items.pop(spi_id, None)
        if item:
            ref_id = item.get("ref_object_id", "")
            ref_type = item.get("ref_object_type", "")
            alias_ids = item.get("ref_alias_ids") or ([ref_id] if ref_id else [])
            for alias_id in alias_ids:
                if alias_id and self._ref_index.get(alias_id) == spi_id:
                    del self._ref_index[alias_id]
            root_structure_id = self._extract_root_structure_id(item)
            if root_structure_id and self._root_structure_index.get(root_structure_id) == spi_id:
                del self._root_structure_index[root_structure_id]
            semantic_signature = item.get("semantic_signature", "")
            if semantic_signature and self._semantic_index.get(semantic_signature) == spi_id:
                del self._semantic_index[semantic_signature]
            semantic_context_key = item.get("semantic_context_key", "")
            if semantic_context_key and self._semantic_context_index.get(semantic_context_key) == spi_id:
                del self._semantic_context_index[semantic_context_key]
            if ref_type and ref_type in self._type_index:
                self._type_index[ref_type].discard(spi_id)
        return item

    def clear(self) -> int:
        """清空全部对象，返回清除数量。"""
        count = len(self._items)
        self._items.clear()
        self._ref_index.clear()
        self._root_structure_index.clear()
        self._semantic_index.clear()
        self._semantic_context_index.clear()
        self._type_index.clear()
        return count

    def bind_ref_alias(self, spi_id: str, ref_object_id: str):
        """把新的 ref_object_id 绑定到已有对象上，支持语义同一对象跨轮次对齐。"""
        if not ref_object_id:
            return
        item = self._items.get(spi_id)
        if not item:
            return
        alias_ids = item.setdefault("ref_alias_ids", [])
        if ref_object_id not in alias_ids:
            alias_ids.append(ref_object_id)
        self._ref_index[ref_object_id] = spi_id

    def bind_root_structure_id(self, spi_id: str, root_structure_id: str):
        """把运行态根结构 ID 绑定到已有对象。"""
        root_structure_id = str(root_structure_id or "").strip()
        if not root_structure_id:
            return
        item = self._items.get(spi_id)
        if not item:
            return
        ext = item.setdefault("ext", {})
        if not isinstance(ext, dict):
            ext = {}
            item["ext"] = ext
        ext["runtime_root_structure_id"] = root_structure_id
        meta = item.setdefault("meta", {})
        if not isinstance(meta, dict):
            meta = {}
            item["meta"] = meta
        meta_ext = meta.setdefault("ext", {})
        if not isinstance(meta_ext, dict):
            meta_ext = {}
            meta["ext"] = meta_ext
        runtime_resolution = meta_ext.setdefault("runtime_resolution", {})
        if not isinstance(runtime_resolution, dict):
            runtime_resolution = {}
            meta_ext["runtime_resolution"] = runtime_resolution
        runtime_resolution["root_structure_id"] = root_structure_id
        self._root_structure_index[root_structure_id] = spi_id

    # ================================================================== #
    #                     排序和查询                                       #
    # ================================================================== #

    def get_sorted(
        self,
        sort_by: str = "cp_abs",
        top_k: int | None = None,
        descending: bool = True,
    ) -> list[dict]:
        """
        返回排序后的对象列表。

        sort_by: cp_abs | er | ev | total_energy | updated_at
        top_k: 返回前 K 个（None=全部）
        """
        key_map = {
            "cp_abs": lambda x: x.get("energy", {}).get("cognitive_pressure_abs", 0),
            "er": lambda x: x.get("energy", {}).get("er", 0),
            "ev": lambda x: x.get("energy", {}).get("ev", 0),
            "total_energy": lambda x: (
                float(x.get("energy", {}).get("er", 0) or 0)
                + float(x.get("energy", {}).get("ev", 0) or 0)
            ),
            "updated_at": lambda x: x.get("updated_at", 0),
        }
        key_fn = key_map.get(sort_by, key_map["cp_abs"])
        if top_k is not None:
            try:
                k = max(0, int(top_k))
            except Exception:
                k = 0
            if k <= 0:
                return []
            if k < len(self._items):
                if descending:
                    return heapq.nlargest(k, self._items.values(), key=key_fn)
                return heapq.nsmallest(k, self._items.values(), key=key_fn)
        items = sorted(self._items.values(), key=key_fn, reverse=descending)
        if top_k is not None:
            items = items[:top_k]
        return items

    def get_high_cp_items(self, threshold: float = 0.5) -> list[dict]:
        """获取认知压幅值高于阈值的对象。"""
        return [
            item for item in self._items.values()
            if item.get("energy", {}).get("cognitive_pressure_abs", 0) >= threshold
        ]

    # ================================================================== #
    #                     内部淘汰                                         #
    # ================================================================== #

    def _prune_lowest_energy(self, count: int = 1) -> int:
        """淘汰最低能量的对象以腾出空间。"""
        if not self._items:
            return 0
        # 按 er+ev 排序，淘汰最低的
        sorted_ids = sorted(
            self._items.keys(),
            key=lambda sid: (
                self._items[sid].get("energy", {}).get("er", 0)
                + self._items[sid].get("energy", {}).get("ev", 0)
            ),
        )
        pruned = 0
        for sid in sorted_ids[:count]:
            self.remove(sid)
            pruned += 1
        return pruned

    def update_config(self, config: dict):
        """更新配置。"""
        self._config = config

    def rebuild_index(self):
        """重建索引（用于故障恢复）。"""
        self._ref_index.clear()
        self._root_structure_index.clear()
        self._semantic_index.clear()
        self._semantic_context_index.clear()
        self._type_index.clear()
        for spi_id, item in self._items.items():
            ref_id = item.get("ref_object_id", "")
            ref_type = item.get("ref_object_type", "")
            alias_ids = item.get("ref_alias_ids") or ([ref_id] if ref_id else [])
            for alias_id in alias_ids:
                if alias_id:
                    self._ref_index[alias_id] = spi_id
            root_structure_id = self._extract_root_structure_id(item)
            if root_structure_id:
                self._root_structure_index[root_structure_id] = spi_id
            semantic_signature = item.get("semantic_signature", "")
            if semantic_signature:
                self._semantic_index[semantic_signature] = spi_id
            semantic_context_key = item.get("semantic_context_key", "")
            if semantic_context_key:
                self._semantic_context_index[semantic_context_key] = spi_id
            if ref_type:
                if ref_type not in self._type_index:
                    self._type_index[ref_type] = set()
                self._type_index[ref_type].add(spi_id)

    def _remove_index_entries_for_spi(self, spi_id: str) -> None:
        for alias_id, owner_spi in list(self._ref_index.items()):
            if owner_spi == spi_id:
                del self._ref_index[alias_id]
        for root_id, owner_spi in list(self._root_structure_index.items()):
            if owner_spi == spi_id:
                del self._root_structure_index[root_id]
        for signature, owner_spi in list(self._semantic_index.items()):
            if owner_spi == spi_id:
                del self._semantic_index[signature]
        for key, owner_spi in list(self._semantic_context_index.items()):
            if owner_spi == spi_id:
                del self._semantic_context_index[key]
        for ref_type, ids in list(self._type_index.items()):
            if isinstance(ids, set):
                ids.discard(spi_id)
                if not ids:
                    del self._type_index[ref_type]

    @staticmethod
    def _extract_root_structure_id(item: dict) -> str:
        """Extract runtime root identity without using growth provenance as identity."""
        if not isinstance(item, dict):
            return ""

        def _from_container(container: dict | None) -> str:
            if not isinstance(container, dict):
                return ""
            runtime_resolution = container.get("runtime_resolution", {})
            if isinstance(runtime_resolution, dict):
                value = str(runtime_resolution.get("root_structure_id", "") or "").strip()
                if value:
                    return value
            value = str(container.get("runtime_root_structure_id", "") or "").strip()
            if value:
                return value
            value = str(container.get("root_structure_id", "") or "").strip()
            return value

        for container in (
            item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {},
            item.get("meta", {}).get("ext", {})
            if isinstance(item.get("meta", {}).get("ext", {}), dict)
            else {},
            item.get("ref_snapshot", {}).get("structure_ext", {})
            if isinstance(item.get("ref_snapshot", {}).get("structure_ext", {}), dict)
            else {},
            item,
        ):
            root_id = _from_container(container)
            if root_id:
                return root_id

        if str(item.get("ref_object_type", "") or "").strip() == "st":
            return str(item.get("ref_object_id", "") or "").strip()
        return ""
