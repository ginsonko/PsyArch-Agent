# -*- coding: utf-8 -*-
"""
Memory activation pool for episodic-memory dual-channel (ER/EV) accumulation.
"""

from __future__ import annotations

import time
from pathlib import Path
import re

from ._storage_utils import list_json_files, load_json_file, remove_file, write_json_file


class MemoryActivationStore:
    def __init__(self, base_dir: str | Path, config: dict):
        self._base_dir = Path(base_dir)
        self._config = config
        self._items: dict[str, dict] = {}
        self._recent_memory_ids: list[str] = []
        self._load()

    @property
    def size(self) -> int:
        return len(self._items)

    def update_config(self, config: dict) -> None:
        self._config = config

    def get(self, memory_id: str) -> dict | None:
        return self._items.get(memory_id)

    def iter_items(self) -> list[dict]:
        return list(self._items.values())

    def get_recent(self, limit: int = 10) -> list[dict]:
        if limit <= 0:
            return []
        recent: list[dict] = []
        for memory_id in reversed(self._recent_memory_ids):
            if len(recent) >= limit:
                break
            item = self._items.get(memory_id)
            if item is not None:
                recent.append(item)
        if len(recent) >= limit:
            return recent[:limit]
        seen = {str(item.get("memory_id", item.get("id", ""))) for item in recent}
        for memory_id in reversed(list(self._items.keys())):
            if len(recent) >= limit:
                break
            if memory_id in seen:
                continue
            item = self._items.get(memory_id)
            if item is not None:
                recent.append(item)
        return recent[:limit]

    def clear(self) -> int:
        count = len(self._items)
        for memory_id in list(self._items):
            self.delete(memory_id)
        self._items.clear()
        self._recent_memory_ids.clear()
        return count

    def delete(self, memory_id: str) -> bool:
        item = self._items.pop(memory_id, None)
        if item is None:
            return False
        try:
            self._recent_memory_ids.remove(memory_id)
        except ValueError:
            pass
        return remove_file(self._file_path(memory_id))

    def apply_targets(
        self,
        *,
        targets: list[dict],
        episodic_store,
        trace_id: str,
        tick_id: str = "",
    ) -> dict:
        now_ms = int(time.time() * 1000)
        aggregated = self._aggregate_targets(targets)
        applied_items: list[dict] = []
        total_delta_er = 0.0
        total_delta_ev = 0.0

        for memory_id, payload in aggregated.items():
            episodic_obj = episodic_store.get(memory_id)
            if episodic_obj is None:
                continue
            item = self._items.get(memory_id)
            if item is None:
                item = self._make_item(
                    memory_id=memory_id,
                    episodic_obj=episodic_obj,
                    display_text=payload.get("display_text", ""),
                    now_ms=now_ms,
                )
            self._apply_aggregate_to_item(
                item=item,
                episodic_obj=episodic_obj,
                payload=payload,
                now_ms=now_ms,
                trace_id=trace_id,
                tick_id=tick_id or trace_id,
            )
            self._items[memory_id] = item
            self._persist_item(item)
            total_delta_er += float(payload.get("delta_er", 0.0))
            total_delta_ev += float(payload.get("delta_ev", 0.0))
            self._touch_recent(memory_id)
            applied_items.append(self._snapshot_item(item))

        applied_items.sort(key=self._energy_desc_key)
        return {
            "applied_count": len(applied_items),
            "total_delta_er": round(total_delta_er, 8),
            "total_delta_ev": round(total_delta_ev, 8),
            "total_delta_energy": round(total_delta_er + total_delta_ev, 8),
            "items": applied_items,
        }

    def tick(self, *, trace_id: str = "", tick_id: str = "") -> dict:
        now_ms = int(time.time() * 1000)
        decay_ratio = min(
            1.0,
            max(0.0, float(self._config.get("memory_activation_decay_round_ratio_ev", 0.93))),
        )
        prune_threshold = max(0.0, float(self._config.get("memory_activation_prune_threshold_ev", 0.03)))
        decayed_count = 0
        pruned_count = 0
        total_er_before = 0.0
        total_ev_before = 0.0
        total_er_after = 0.0
        total_ev_after = 0.0

        for memory_id in list(self._items):
            item = self._items.get(memory_id)
            if not item:
                continue
            before_er = max(0.0, float(item.get("er", 0.0)))
            before_ev = max(0.0, float(item.get("ev", 0.0)))
            total_er_before += before_er
            total_ev_before += before_ev
            after_er = round(before_er * decay_ratio, 8)
            after_ev = round(before_ev * decay_ratio, 8)
            item["er"] = after_er
            item["ev"] = after_ev
            item["last_decay_delta_er"] = round(after_er - before_er, 8)
            item["last_decay_delta_ev"] = round(after_ev - before_ev, 8)
            item["last_maintained_at"] = now_ms
            item["last_maintenance_trace_id"] = trace_id
            item["last_maintenance_tick_id"] = tick_id or trace_id
            decayed_count += 1
            if after_er <= prune_threshold and after_ev <= prune_threshold:
                self.delete(memory_id)
                pruned_count += 1
                continue
            total_er_after += after_er
            total_ev_after += after_ev
            self._persist_item(item)

        return {
            "decayed_count": decayed_count,
            "pruned_count": pruned_count,
            "total_er_before": round(total_er_before, 8),
            "total_ev_before": round(total_ev_before, 8),
            "total_energy_before": round(total_er_before + total_ev_before, 8),
            "total_er_after": round(total_er_after, 8),
            "total_ev_after": round(total_ev_after, 8),
            "total_energy_after": round(total_er_after + total_ev_after, 8),
        }

    def snapshot(
        self,
        *,
        episodic_store,
        limit: int = 16,
        sort_by: str = "energy_desc",
    ) -> dict:
        items = [self._enrich_from_episodic(dict(item), episodic_store) for item in self._items.values()]
        items.sort(key=self._sort_key(sort_by))
        if limit > 0:
            items = items[:limit]
        total_er = round(sum(float(item.get("er", 0.0)) for item in self._items.values()), 8)
        total_ev = round(sum(float(item.get("ev", 0.0)) for item in self._items.values()), 8)
        return {
            "sort_by": sort_by,
            "available_sorts": ["energy_desc", "recent_desc"],
            "summary": {
                "count": len(self._items),
                "total_er": total_er,
                "total_ev": total_ev,
                "total_energy": round(total_er + total_ev, 8),
                "top_total_energy": round(self._total_energy(items[0]), 8) if items else 0.0,
            },
            "items": [self._snapshot_item(item) for item in items],
        }

    def query(self, *, memory_id: str, episodic_store) -> dict | None:
        item = self._items.get(memory_id)
        if item is None:
            return None
        return self._snapshot_item(self._enrich_from_episodic(dict(item), episodic_store))

    def record_feedback(
        self,
        *,
        feedback_items: list[dict],
        episodic_store,
        trace_id: str,
        tick_id: str = "",
    ) -> dict:
        now_ms = int(time.time() * 1000)
        updated_items: list[dict] = []
        total_feedback_er = 0.0
        total_feedback_ev = 0.0

        for payload in feedback_items or []:
            memory_id = str(payload.get("memory_id", ""))
            if not memory_id:
                continue
            item = self._items.get(memory_id)
            episodic_obj = episodic_store.get(memory_id)
            if item is None or episodic_obj is None:
                continue
            delta_er = round(max(0.0, float(payload.get("delta_er", 0.0))), 8)
            delta_ev = round(max(0.0, float(payload.get("delta_ev", 0.0))), 8)
            if delta_er <= 0.0 and delta_ev <= 0.0:
                continue
            total_feedback_er += delta_er
            total_feedback_ev += delta_ev
            item.setdefault("feedback_count", 0)
            item.setdefault("last_feedback_er", 0.0)
            item.setdefault("last_feedback_ev", 0.0)
            item.setdefault("total_feedback_er", 0.0)
            item.setdefault("total_feedback_ev", 0.0)
            item.setdefault("last_feedback_at", 0)
            item.setdefault("recent_feedback_events", [])
            item["feedback_count"] = int(item.get("feedback_count", 0)) + 1
            item["last_feedback_er"] = delta_er
            item["last_feedback_ev"] = delta_ev
            item["total_feedback_er"] = round(float(item.get("total_feedback_er", 0.0)) + delta_er, 8)
            item["total_feedback_ev"] = round(float(item.get("total_feedback_ev", 0.0)) + delta_ev, 8)
            item["last_feedback_at"] = now_ms

            recent_feedback_events = list(item.get("recent_feedback_events", []))
            recent_feedback_events.append(
                {
                    "timestamp_ms": now_ms,
                    "trace_id": trace_id,
                    "tick_id": tick_id or trace_id,
                    "delta_er": delta_er,
                    "delta_ev": delta_ev,
                    "feedback_kind": str(payload.get("feedback_kind", "")),
                    "target_count": int(payload.get("target_count", 0)),
                    "grouped_display_text": str(payload.get("grouped_display_text", "")),
                    "target_display_texts": [str(value) for value in payload.get("target_display_texts", []) if str(value)],
                }
            )
            history_limit = max(1, int(self._config.get("memory_activation_event_history_limit", 24)))
            item["recent_feedback_events"] = recent_feedback_events[-history_limit:]
            self._persist_item(item)
            updated_items.append(self._snapshot_item(self._enrich_from_episodic(dict(item), episodic_store)))

        updated_items.sort(key=self._energy_desc_key)
        return {
            "recorded_count": len(updated_items),
            "total_feedback_er": round(total_feedback_er, 8),
            "total_feedback_ev": round(total_feedback_ev, 8),
            "total_feedback_energy": round(total_feedback_er + total_feedback_ev, 8),
            "items": updated_items,
        }

    def _aggregate_targets(self, targets: list[dict]) -> dict[str, dict]:
        aggregated: dict[str, dict] = {}
        for target in targets or []:
            if str(target.get("projection_kind", "structure")) != "memory":
                continue
            memory_id = str(target.get("memory_id", ""))
            delta_er = max(0.0, float(target.get("delta_er", 0.0)))
            delta_ev = max(0.0, float(target.get("delta_ev", 0.0)))
            if not memory_id or (delta_er <= 0.0 and delta_ev <= 0.0):
                continue
            bucket = aggregated.setdefault(
                memory_id,
                {
                    "memory_id": memory_id,
                    "display_text": str(target.get("target_display_text", "")),
                    "delta_er": 0.0,
                    "delta_ev": 0.0,
                    "hit_count": 0,
                    "mode_totals": {},
                    "mode_totals_er": {},
                    "mode_totals_ev": {},
                    "backing_structure_ids": [],
                    "source_structure_ids": [],
                },
            )
            bucket["delta_er"] += delta_er
            bucket["delta_ev"] += delta_ev
            bucket["hit_count"] += 1
            backing_structure_id = str(target.get("backing_structure_id", ""))
            if backing_structure_id:
                bucket["backing_structure_ids"].append(backing_structure_id)
            for source_id in target.get("sources", []) or []:
                if source_id:
                    bucket["source_structure_ids"].append(str(source_id))
            mode_items = target.get("modes", []) or ([target.get("mode")] if target.get("mode") else [])
            for mode in mode_items:
                mode_key = str(mode or "")
                if not mode_key:
                    continue
                bucket["mode_totals"][mode_key] = round(
                    float(bucket["mode_totals"].get(mode_key, 0.0)) + delta_er + delta_ev,
                    8,
                )
                bucket["mode_totals_er"][mode_key] = round(
                    float(bucket["mode_totals_er"].get(mode_key, 0.0)) + delta_er,
                    8,
                )
                bucket["mode_totals_ev"][mode_key] = round(
                    float(bucket["mode_totals_ev"].get(mode_key, 0.0)) + delta_ev,
                    8,
                )

        for payload in aggregated.values():
            payload["delta_er"] = round(float(payload.get("delta_er", 0.0)), 8)
            payload["delta_ev"] = round(float(payload.get("delta_ev", 0.0)), 8)
            payload["backing_structure_ids"] = self._dedupe(payload.get("backing_structure_ids", []))
            payload["source_structure_ids"] = self._dedupe(payload.get("source_structure_ids", []))
        return aggregated

    def _make_item(self, *, memory_id: str, episodic_obj: dict, display_text: str, now_ms: int) -> dict:
        ext = dict(episodic_obj.get("meta", {}).get("ext", {}) or {})
        memory_material = dict(ext.get("memory_material", {}) or {})
        grouped_display_text = str(memory_material.get("grouped_display_text", "") or "")
        memory_kind = str(memory_material.get("memory_kind", "") or "")
        sequence_groups = list(memory_material.get("sequence_groups", []) or [])
        resolved_display = (
            str(display_text or "")
            or grouped_display_text
            or str(ext.get("display_text", ""))
            or str(episodic_obj.get("event_summary", ""))
            or memory_id
        )
        return {
            "id": memory_id,
            "object_type": "memory_activation",
            "memory_id": memory_id,
            "display_text": resolved_display,
            "grouped_display_text": grouped_display_text,
            "memory_kind": memory_kind,
            "sequence_groups": sequence_groups,
            "memory_material": memory_material,
            "event_summary": str(episodic_obj.get("event_summary", "")),
            "structure_refs": list(episodic_obj.get("structure_refs", [])),
            "group_refs": list(episodic_obj.get("group_refs", [])),
            "backing_structure_ids": [],
            "source_structure_ids": [],
            "er": 0.0,
            "ev": 0.0,
            "last_delta_er": 0.0,
            "last_delta_ev": 0.0,
            "last_decay_delta_er": 0.0,
            "last_decay_delta_ev": 0.0,
            "total_delta_er": 0.0,
            "total_delta_ev": 0.0,
            "hit_count": 0,
            "update_count": 0,
            "mode_totals": {
                "ev_propagation": 0.0,
                "er_induction": 0.0,
            },
            "mode_totals_er": {
                "ev_propagation": 0.0,
                "er_induction": 0.0,
            },
            "mode_totals_ev": {
                "ev_propagation": 0.0,
                "er_induction": 0.0,
            },
            "recent_events": [],
            "feedback_count": 0,
            "last_feedback_er": 0.0,
            "last_feedback_ev": 0.0,
            "total_feedback_er": 0.0,
            "total_feedback_ev": 0.0,
            "last_feedback_at": 0,
            "recent_feedback_events": [],
            "created_at": now_ms,
            "last_updated_at": now_ms,
            "last_trace_id": "",
            "last_tick_id": "",
        }

    def _apply_aggregate_to_item(
        self,
        *,
        item: dict,
        episodic_obj: dict,
        payload: dict,
        now_ms: int,
        trace_id: str,
        tick_id: str,
    ) -> None:
        ext = dict(episodic_obj.get("meta", {}).get("ext", {}) or {})
        memory_material = dict(ext.get("memory_material", {}) or {})
        grouped_display_text = str(memory_material.get("grouped_display_text", "") or "")
        memory_kind = str(memory_material.get("memory_kind", "") or "")
        sequence_groups = list(memory_material.get("sequence_groups", []) or [])
        delta_er = round(max(0.0, float(payload.get("delta_er", 0.0))), 8)
        delta_ev = round(max(0.0, float(payload.get("delta_ev", 0.0))), 8)
        if delta_er <= 0.0 and delta_ev <= 0.0:
            return
        item["display_text"] = (
            grouped_display_text
            or str(payload.get("display_text", ""))
            or str(item.get("display_text", ""))
            or str(episodic_obj.get("event_summary", ""))
            or str(item.get("memory_id", ""))
        )
        item["grouped_display_text"] = grouped_display_text or str(item.get("grouped_display_text", ""))
        item["memory_kind"] = memory_kind or str(item.get("memory_kind", ""))
        item["sequence_groups"] = sequence_groups or list(item.get("sequence_groups", []) or [])
        item["memory_material"] = memory_material or dict(item.get("memory_material", {}) or {})
        item["event_summary"] = str(episodic_obj.get("event_summary", ""))
        item["structure_refs"] = list(episodic_obj.get("structure_refs", []))
        item["group_refs"] = list(episodic_obj.get("group_refs", []))
        item["er"] = round(max(0.0, float(item.get("er", 0.0))) + delta_er, 8)
        item["ev"] = round(max(0.0, float(item.get("ev", 0.0))) + delta_ev, 8)
        item["last_delta_er"] = delta_er
        item["last_delta_ev"] = delta_ev
        item["last_decay_delta_er"] = 0.0
        item["last_decay_delta_ev"] = 0.0
        item["total_delta_er"] = round(float(item.get("total_delta_er", 0.0)) + delta_er, 8)
        item["total_delta_ev"] = round(float(item.get("total_delta_ev", 0.0)) + delta_ev, 8)
        item["hit_count"] = int(item.get("hit_count", 0)) + int(payload.get("hit_count", 0))
        item["update_count"] = int(item.get("update_count", 0)) + 1
        item["last_updated_at"] = now_ms
        item["last_trace_id"] = trace_id
        item["last_tick_id"] = tick_id
        item["backing_structure_ids"] = self._merge_capped_unique(
            item.get("backing_structure_ids", []),
            payload.get("backing_structure_ids", []),
            cap=32,
        )
        item["source_structure_ids"] = self._merge_capped_unique(
            item.get("source_structure_ids", []),
            payload.get("source_structure_ids", []),
            cap=32,
        )
        mode_totals = dict(item.get("mode_totals", {}))
        for mode, mode_delta in dict(payload.get("mode_totals", {})).items():
            mode_totals[str(mode)] = round(float(mode_totals.get(str(mode), 0.0)) + float(mode_delta), 8)
        item["mode_totals"] = mode_totals
        mode_totals_er = dict(item.get("mode_totals_er", {}))
        for mode, mode_delta in dict(payload.get("mode_totals_er", {})).items():
            mode_totals_er[str(mode)] = round(float(mode_totals_er.get(str(mode), 0.0)) + float(mode_delta), 8)
        item["mode_totals_er"] = mode_totals_er
        mode_totals_ev = dict(item.get("mode_totals_ev", {}))
        for mode, mode_delta in dict(payload.get("mode_totals_ev", {})).items():
            mode_totals_ev[str(mode)] = round(float(mode_totals_ev.get(str(mode), 0.0)) + float(mode_delta), 8)
        item["mode_totals_ev"] = mode_totals_ev

        recent_events = list(item.get("recent_events", []))
        recent_events.append(
            {
                "timestamp_ms": now_ms,
                "trace_id": trace_id,
                "tick_id": tick_id,
                "delta_er": delta_er,
                "delta_ev": delta_ev,
                "mode_totals": dict(payload.get("mode_totals", {})),
                "mode_totals_er": dict(payload.get("mode_totals_er", {})),
                "mode_totals_ev": dict(payload.get("mode_totals_ev", {})),
                "source_structure_ids": list(payload.get("source_structure_ids", [])),
                "backing_structure_ids": list(payload.get("backing_structure_ids", [])),
            }
        )
        history_limit = max(1, int(self._config.get("memory_activation_event_history_limit", 24)))
        item["recent_events"] = recent_events[-history_limit:]

    def _enrich_from_episodic(self, item: dict, episodic_store) -> dict:
        memory_id = str(item.get("memory_id", item.get("id", "")))
        episodic_obj = episodic_store.get(memory_id)
        if episodic_obj is None:
            return item
        # Align to theory core 4.2.6.3:
        # time-feeling delta should be based on the *memory* timestamp, not the MAP entry creation time.
        # ????????? 4.2.6.3??
        # ???????????????????????????????????????MAP ???????????
        try:
            item["memory_created_at"] = int(episodic_obj.get("created_at", 0) or 0)
        except Exception:
            item["memory_created_at"] = int(item.get("created_at", 0) or 0)
        item["memory_tick_id"] = str(episodic_obj.get("tick_id", "") or "")
        item["memory_trace_id"] = str(episodic_obj.get("trace_id", "") or "")
        tick_id = str(episodic_obj.get("tick_id", "") or "")
        m = re.search(r"(\d+)$", tick_id)
        try:
            item["memory_tick_index"] = int(m.group(1)) if m else 0
        except Exception:
            item["memory_tick_index"] = 0
        item["event_summary"] = str(episodic_obj.get("event_summary", ""))
        item["structure_refs"] = list(episodic_obj.get("structure_refs", []))
        item["group_refs"] = list(episodic_obj.get("group_refs", []))
        ext = dict(episodic_obj.get("meta", {}).get("ext", {}) or {})
        memory_material = dict(ext.get("memory_material", {}) or {})
        grouped_display_text = str(memory_material.get("grouped_display_text", "") or "")
        memory_kind = str(memory_material.get("memory_kind", "") or "")
        sequence_groups = list(memory_material.get("sequence_groups", []) or [])
        if memory_material:
            item["memory_material"] = memory_material
        if grouped_display_text:
            item["grouped_display_text"] = grouped_display_text
            item["display_text"] = grouped_display_text
        if memory_kind:
            item["memory_kind"] = memory_kind
        if sequence_groups:
            item["sequence_groups"] = sequence_groups
        if not str(item.get("display_text", "")):
            item["display_text"] = (
                grouped_display_text
                or str(ext.get("display_text", ""))
                or str(episodic_obj.get("event_summary", ""))
                or memory_id
            )
        return item

    @staticmethod
    def _snapshot_item(item: dict) -> dict:
        return {
            "memory_id": str(item.get("memory_id", item.get("id", ""))),
            "display_text": str(item.get("grouped_display_text", "") or item.get("display_text", "")),
            "grouped_display_text": str(item.get("grouped_display_text", "")) or None,
            "memory_kind": str(item.get("memory_kind", "")) or None,
            "sequence_groups": list(item.get("sequence_groups", []) or []),
            "memory_material": dict(item.get("memory_material", {}) or {}),
            "event_summary": str(item.get("event_summary", "")),
            "structure_refs": list(item.get("structure_refs", [])),
            "group_refs": list(item.get("group_refs", [])),
            "backing_structure_ids": list(item.get("backing_structure_ids", [])),
            "source_structure_ids": list(item.get("source_structure_ids", [])),
            "er": round(float(item.get("er", 0.0)), 8),
            "ev": round(float(item.get("ev", 0.0)), 8),
            "total_energy": round(MemoryActivationStore._total_energy(item), 8),
            "last_delta_er": round(float(item.get("last_delta_er", 0.0)), 8),
            "last_delta_ev": round(float(item.get("last_delta_ev", 0.0)), 8),
            "last_decay_delta_er": round(float(item.get("last_decay_delta_er", 0.0)), 8),
            "last_decay_delta_ev": round(float(item.get("last_decay_delta_ev", 0.0)), 8),
            "total_delta_er": round(float(item.get("total_delta_er", 0.0)), 8),
            "total_delta_ev": round(float(item.get("total_delta_ev", 0.0)), 8),
            "hit_count": int(item.get("hit_count", 0)),
            "update_count": int(item.get("update_count", 0)),
            "mode_totals": dict(item.get("mode_totals", {})),
            "mode_totals_er": dict(item.get("mode_totals_er", {})),
            "mode_totals_ev": dict(item.get("mode_totals_ev", {})),
            "recent_events": list(item.get("recent_events", [])),
            "feedback_count": int(item.get("feedback_count", 0)),
            "last_feedback_er": round(float(item.get("last_feedback_er", 0.0)), 8),
            "last_feedback_ev": round(float(item.get("last_feedback_ev", 0.0)), 8),
            "total_feedback_er": round(float(item.get("total_feedback_er", 0.0)), 8),
            "total_feedback_ev": round(float(item.get("total_feedback_ev", 0.0)), 8),
            "last_feedback_at": int(item.get("last_feedback_at", 0)),
            "recent_feedback_events": list(item.get("recent_feedback_events", [])),
            "created_at": int(item.get("created_at", 0)),
            "memory_created_at": int(item.get("memory_created_at", item.get("created_at", 0)) or 0),
            "memory_tick_id": str(item.get("memory_tick_id", "") or ""),
            "memory_trace_id": str(item.get("memory_trace_id", "") or ""),
            "memory_tick_index": int(item.get("memory_tick_index", 0) or 0),
            "last_updated_at": int(item.get("last_updated_at", 0)),
            "last_trace_id": str(item.get("last_trace_id", "")),
            "last_tick_id": str(item.get("last_tick_id", "")),
        }

    def _load(self) -> None:
        for path in list_json_files(self._base_dir):
            payload = load_json_file(path, default=None)
            if not isinstance(payload, dict) or not payload.get("memory_id"):
                continue
            memory_id = str(payload["memory_id"])
            self._items[memory_id] = payload
            self._recent_memory_ids.append(memory_id)
        self._recent_memory_ids.sort(
            key=lambda memory_id: (
                int(self._items.get(memory_id, {}).get("last_updated_at", 0) or 0),
                int(self._items.get(memory_id, {}).get("created_at", 0) or 0),
                str(memory_id),
            )
        )

    def _touch_recent(self, memory_id: str) -> None:
        try:
            self._recent_memory_ids.remove(memory_id)
        except ValueError:
            pass
        self._recent_memory_ids.append(memory_id)

    def _persist_item(self, item: dict) -> None:
        write_json_file(self._file_path(item.get("memory_id", "")), item)

    def _file_path(self, memory_id: str) -> Path:
        return self._base_dir / f"{memory_id}.json"

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        return list(dict.fromkeys(str(value) for value in values if str(value)))

    def _merge_capped_unique(self, existing: list[str], incoming: list[str], *, cap: int) -> list[str]:
        merged = self._dedupe(list(existing or []) + list(incoming or []))
        if len(merged) <= cap:
            return merged
        return merged[-cap:]

    @staticmethod
    def _energy_desc_key(item: dict) -> tuple[float, float, str]:
        return (
            -MemoryActivationStore._total_energy(item),
            -float(item.get("last_updated_at", 0.0)),
            str(item.get("memory_id", item.get("id", ""))),
        )

    @staticmethod
    def _recent_desc_key(item: dict) -> tuple[float, float, str]:
        return (
            -float(item.get("last_updated_at", 0.0)),
            -MemoryActivationStore._total_energy(item),
            str(item.get("memory_id", item.get("id", ""))),
        )

    @staticmethod
    def _total_energy(item: dict) -> float:
        return round(max(0.0, float(item.get("er", 0.0))) + max(0.0, float(item.get("ev", 0.0))), 8)

    def _sort_key(self, sort_by: str):
        if sort_by == "recent_desc":
            return self._recent_desc_key
        return self._energy_desc_key




