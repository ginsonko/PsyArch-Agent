# -*- coding: utf-8 -*-
"""
Structure group store for HDB.
"""

from __future__ import annotations

import time
from collections import defaultdict
from itertools import islice
from pathlib import Path

from . import __schema_version__, __module_name__
from ._id_generator import ensure_counter, next_id
from ._storage_utils import list_json_files, load_json_file, remove_file, write_json_file


class GroupStore:
    def __init__(self, base_dir: str | Path, config: dict | None = None):
        self._base_dir = Path(base_dir)
        self._config = config or {}
        self._items: dict[str, dict] = {}
        self._recent_group_ids: list[str] = []
        self._group_index_keys: dict[str, dict[str, tuple[str, ...] | str]] = {}
        self._signature_index: dict[str, set[str]] = defaultdict(set)
        self._required_structure_index: dict[str, set[str]] = defaultdict(set)
        self._load()

    @property
    def size(self) -> int:
        return len(self._items)

    def _recency_peak(self) -> float:
        return max(1.0, float(self._config.get("recency_gain_peak", 10.0)))

    def _recency_hold_rounds(self) -> int:
        return max(0, int(self._config.get("recency_gain_hold_rounds", 2)))

    def _new_recent_gain(self) -> float:
        return round(self._recency_peak(), 8)

    def create_group(
        self,
        required_structure_ids: list[str],
        avg_energy_profile: dict[str, float],
        trace_id: str,
        tick_id: str = "",
        *,
        bias_structure_ids: list[str] | None = None,
        source_interface: str = "run_structure_level_retrieval_storage",
        origin: str = "learned_from_cam",
        origin_id: str = "",
        metadata: dict | None = None,
    ) -> dict:
        now_ms = int(time.time() * 1000)
        group_id = next_id("sg")
        item = {
            "id": group_id,
            "object_type": "sg",
            "sub_type": "event_template_group",
            "schema_version": __schema_version__,
            "required_structure_ids": list(dict.fromkeys(required_structure_ids)),
            "bias_structure_ids": list(dict.fromkeys(bias_structure_ids or [])),
            "avg_energy_profile": dict(avg_energy_profile),
            "stats": {
                "base_weight": 1.0,
                "recent_gain": self._new_recent_gain(),
                "fatigue": 0.0,
                "match_count_total": 0,
                "last_matched_at": 0,
                "last_recency_refresh_at": now_ms,
                "recency_hold_rounds_remaining": self._recency_hold_rounds(),
                "created_from_structure_count": len(required_structure_ids),
            },
            "source": {
                "module": __module_name__,
                "interface": source_interface,
                "origin": origin,
                "origin_id": origin_id,
                "parent_ids": list(required_structure_ids),
            },
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "meta": metadata
            or {
                "confidence": 0.75,
                "field_registry_version": __schema_version__,
                "debug": {},
                "ext": {},
            },
        }
        self._items[group_id] = item
        self._recent_group_ids.append(group_id)
        self._index_group(item)
        self._persist_item(item)
        return item

    def get(self, group_id: str) -> dict | None:
        return self._items.get(group_id)

    def iter_items(self) -> list[dict]:
        return list(self._items.values())

    def update(self, item: dict) -> None:
        if not item.get("id"):
            return
        item["updated_at"] = int(time.time() * 1000)
        group_id = str(item["id"])
        self._unindex_group(group_id)
        self._items[group_id] = item
        self._index_group(item)
        self._persist_item(item)

    def update_config(self, config: dict) -> None:
        self._config = config or {}

    def delete(self, group_id: str) -> bool:
        item = self._items.pop(group_id, None)
        if item is None:
            return False
        self._unindex_group(group_id)
        try:
            self._recent_group_ids.remove(group_id)
        except ValueError:
            pass
        return remove_file(self._file_path(group_id))

    def clear(self) -> int:
        count = len(self._items)
        for group_id in list(self._items):
            self.delete(group_id)
        self._items.clear()
        self._recent_group_ids.clear()
        self._group_index_keys.clear()
        self._signature_index.clear()
        self._required_structure_index.clear()
        return count

    def get_recent(self, limit: int = 10) -> list[dict]:
        if limit <= 0:
            return []
        recent = [
            self._items[group_id]
            for group_id in islice(reversed(self._recent_group_ids), limit)
            if group_id in self._items
        ]
        if len(recent) >= limit:
            return recent[:limit]
        seen = {str(item.get("id", "")) for item in recent}
        for group_id in reversed(list(self._items.keys())):
            if len(recent) >= limit:
                break
            if group_id in seen:
                continue
            item = self._items.get(group_id)
            if item is not None:
                recent.append(item)
        return recent[:limit]

    def query_by_signature(self, signature: str, limit: int | None = None) -> list[dict]:
        signature = str(signature or "").strip()
        if not signature:
            return []
        return self._items_from_ids(self._signature_index.get(signature, set()), limit=limit)

    def query_by_required_structures(self, required_structure_ids: list[str], limit: int | None = None) -> list[dict]:
        required_ids = [str(structure_id) for structure_id in required_structure_ids if str(structure_id)]
        if not required_ids:
            return []
        indexed_buckets = [
            set(self._required_structure_index.get(structure_id, set()))
            for structure_id in required_ids
        ]
        indexed_buckets.sort(key=len)
        candidate_ids: set[str] | None = None
        for ids_for_structure in indexed_buckets:
            if candidate_ids is None:
                candidate_ids = ids_for_structure
            else:
                candidate_ids.intersection_update(ids_for_structure)
            if not candidate_ids:
                return []
        return self._items_from_ids(candidate_ids or set(), limit=limit)

    def _items_from_ids(self, group_ids: set[str], *, limit: int | None = None) -> list[dict]:
        if not group_ids:
            return []
        ordered = sorted(
            (self._items[group_id] for group_id in group_ids if group_id in self._items),
            key=lambda item: (
                int(item.get("updated_at", item.get("created_at", 0)) or 0),
                int(item.get("created_at", 0) or 0),
                str(item.get("id", "")),
            ),
            reverse=True,
        )
        if limit is not None and limit > 0:
            return ordered[:limit]
        return ordered

    def _group_signature(self, item: dict) -> str:
        signature = str(item.get("group_structure", {}).get("content_signature", "") or "").strip()
        if not signature:
            signature = str(item.get("meta", {}).get("ext", {}).get("group_signature", "") or "").strip()
        return signature

    def _required_structure_ids(self, item: dict) -> tuple[str, ...]:
        return tuple(dict.fromkeys(str(value) for value in item.get("required_structure_ids", []) if str(value)))

    def _index_group(self, item: dict) -> None:
        group_id = str(item.get("id", "") or "")
        if not group_id:
            return
        signature = self._group_signature(item)
        required_ids = self._required_structure_ids(item)
        self._group_index_keys[group_id] = {
            "signature": signature,
            "required_structure_ids": required_ids,
        }
        if signature:
            self._signature_index[signature].add(group_id)
        for structure_id in required_ids:
            self._required_structure_index[structure_id].add(group_id)

    def _unindex_group(self, group_id: str) -> None:
        keys = self._group_index_keys.pop(str(group_id), None)
        if not isinstance(keys, dict):
            return
        signature = str(keys.get("signature", "") or "")
        if signature:
            bucket = self._signature_index.get(signature)
            if bucket is not None:
                bucket.discard(group_id)
                if not bucket:
                    self._signature_index.pop(signature, None)
        for structure_id in keys.get("required_structure_ids", ()) or ():
            bucket = self._required_structure_index.get(str(structure_id))
            if bucket is not None:
                bucket.discard(group_id)
                if not bucket:
                    self._required_structure_index.pop(str(structure_id), None)

    def _file_path(self, group_id: str) -> Path:
        return self._base_dir / f"{group_id}.json"

    def _persist_item(self, item: dict) -> None:
        write_json_file(self._file_path(item["id"]), item)

    def _load(self) -> None:
        for path in list_json_files(self._base_dir):
            payload = load_json_file(path, default=None)
            if not isinstance(payload, dict) or not payload.get("id"):
                continue
            group_id = payload["id"]
            self._items[group_id] = payload
            self._recent_group_ids.append(group_id)
            self._index_group(payload)
            numeric_tail = group_id.rsplit("_", 1)[-1]
            if numeric_tail.isdigit():
                ensure_counter("sg", int(numeric_tail))
        self._recent_group_ids.sort(
            key=lambda group_id: (
                int(self._items.get(group_id, {}).get("created_at", 0) or 0),
                str(group_id),
            )
        )
