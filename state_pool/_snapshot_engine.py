# -*- coding: utf-8 -*-
"""
AP 状态池模块 — 快照引擎
==========================
生成状态池的各种快照结构：
  - state_snapshot（供调试/测试/前端展示）
  - script_check_packet（供脚本检查抄送）
  - attention_snapshot（供注意力过滤器）
"""

import heapq
import time
from ._id_generator import next_id
from . import __schema_version__
from hdb._context_metadata import (
    context_path_depth,
    extract_context_metadata,
    extract_residual_metadata,
)


class SnapshotEngine:
    """
    快照引擎。

    负责从当前池状态和事件窗口中导出各类快照结构。
    """

    def __init__(self, config: dict):
        self._config = config
        self._item_summary_cache: dict[tuple, dict] = {}
        self._item_summary_cache_order: list[tuple] = []

    @staticmethod
    def _infer_type_from_id(identifier: str) -> str:
        text = str(identifier or "")
        if text.startswith("sa_"):
            return "sa"
        if text.startswith("csa_"):
            return "csa"
        if text.startswith("st_"):
            return "st"
        if text.startswith("sg_"):
            return "sg"
        if text.startswith("em_"):
            return "em"
        return ""

    @staticmethod
    def _id_list(values) -> list[str]:
        if values is None:
            return []
        if isinstance(values, (list, tuple, set)):
            iterable = values
        else:
            iterable = [values]
        out: list[str] = []
        seen: set[str] = set()
        for value in iterable:
            text = str(value or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            out.append(text)
        return out

    @classmethod
    def _context_metadata_fast(cls, item: dict) -> dict:
        if not isinstance(item, dict):
            return {
                "context_ref_object_id": "",
                "context_ref_object_type": "",
                "context_owner_structure_id": "",
                "context_path_ids": [],
            }
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        ref_id = str(
            ref_snapshot.get("context_ref_object_id", "")
            or ext.get("context_ref_object_id", "")
            or source.get("context_ref_object_id", "")
            or ""
        ).strip()
        ref_type = str(
            ref_snapshot.get("context_ref_object_type", "")
            or ext.get("context_ref_object_type", "")
            or source.get("context_ref_object_type", "")
            or ""
        ).strip()
        owner_id = str(
            ref_snapshot.get("context_owner_id", "")
            or ref_snapshot.get("context_owner_structure_id", "")
            or ext.get("context_owner_structure_id", "")
            or source.get("context_owner_structure_id", "")
            or ""
        ).strip()
        path_ids = (
            cls._id_list(ref_snapshot.get("context_path_ids", []))
            or cls._id_list(ext.get("context_path_ids", []))
            or cls._id_list(source.get("context_path_ids", []))
            or cls._id_list(source.get("parent_ids", []))
        )
        if owner_id and owner_id not in path_ids:
            path_ids.insert(0, owner_id)
        if not ref_id and path_ids:
            ref_id = path_ids[0]
        if not ref_type and ref_id:
            ref_type = cls._infer_type_from_id(ref_id)
        if not owner_id:
            for candidate_id in path_ids:
                if cls._infer_type_from_id(candidate_id) == "st":
                    owner_id = candidate_id
                    break
        return {
            "context_ref_object_id": ref_id,
            "context_ref_object_type": ref_type,
            "context_owner_structure_id": owner_id,
            "context_path_ids": path_ids,
        }

    @classmethod
    def _explicit_context_metadata_fast(cls, item: dict) -> dict:
        if not isinstance(item, dict):
            return {
                "context_ref_object_id": "",
                "context_ref_object_type": "",
                "context_owner_structure_id": "",
                "context_path_ids": [],
            }
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        source = item.get("source", {}) if isinstance(item.get("source", {}), dict) else {}
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}), dict) and isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
        explicit_marker = ref_snapshot.get("context_explicit", meta_ext.get("context_explicit", None))
        if explicit_marker is False:
            return {
                "context_ref_object_id": "",
                "context_ref_object_type": "",
                "context_owner_structure_id": "",
                "context_path_ids": [],
            }
        ref_id = str(
            ref_snapshot.get("context_ref_object_id", "")
            or ext.get("context_ref_object_id", "")
            or source.get("context_ref_object_id", "")
            or ""
        ).strip()
        ref_type = str(
            ref_snapshot.get("context_ref_object_type", "")
            or ext.get("context_ref_object_type", "")
            or source.get("context_ref_object_type", "")
            or ""
        ).strip()
        owner_id = str(
            ref_snapshot.get("context_owner_id", "")
            or ref_snapshot.get("context_owner_structure_id", "")
            or ext.get("context_owner_structure_id", "")
            or source.get("context_owner_structure_id", "")
            or ""
        ).strip()
        path_ids = (
            cls._id_list(ref_snapshot.get("context_path_ids", []))
            or cls._id_list(ext.get("context_path_ids", []))
            or cls._id_list(source.get("context_path_ids", []))
        )
        if owner_id and owner_id not in path_ids:
            path_ids.insert(0, owner_id)
        if not ref_type and ref_id:
            ref_type = cls._infer_type_from_id(ref_id)
        return {
            "context_ref_object_id": ref_id,
            "context_ref_object_type": ref_type,
            "context_owner_structure_id": owner_id,
            "context_path_ids": path_ids,
        }

    @staticmethod
    def _residual_metadata_fast(item: dict) -> dict:
        if not isinstance(item, dict):
            return {"residual_origin_kind": "", "residual_origin_entry_id": ""}
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        residual_kind = str(
            ref_snapshot.get("residual_origin_kind", "")
            or ext.get("residual_origin_kind", "")
            or ref_snapshot.get("residual_kind", "")
            or ""
        ).strip()
        residual_entry_id = str(
            ref_snapshot.get("residual_origin_entry_id", "")
            or ext.get("residual_origin_entry_id", "")
            or ""
        ).strip()
        relation_type = str(ext.get("relation_type", "") or "").strip()
        if not residual_kind and "residual" in relation_type:
            residual_kind = relation_type
        return {
            "residual_origin_kind": residual_kind,
            "residual_origin_entry_id": residual_entry_id,
        }

    def build_state_snapshot(
        self,
        pool_store,
        history_window,
        trace_id: str,
        tick_id: str = "",
        include_items: bool = True,
        include_history_window: bool = True,
        top_k: int | None = None,
        sort_by: str = "cp_abs",
        runtime_stats: dict | None = None,
    ) -> dict:
        """生成状态池快照。"""
        all_items = pool_store.get_all()

        # 统计
        high_er_count = 0
        high_ev_count = 0
        high_cp_count = 0
        type_counts: dict[str, int] = {}
        energy_by_type: dict[str, dict] = {}
        bound_attribute_item_count = 0
        binding_csa_item_count = 0
        bound_attribute_energy_totals: dict[str, dict] = {}
        contextual_item_count = 0
        explicit_context_item_count = 0
        multi_context_item_count = 0
        residual_origin_item_count = 0
        runtime_resolution_degraded_item_count = 0
        runtime_resolution_active_component_count = 0
        runtime_resolution_dropped_component_count = 0
        context_path_depth_total = 0
        explicit_context_path_depth_total = 0
        total_er = 0.0
        total_ev = 0.0
        total_cp = 0.0
        item_energy_values: list[float] = []
        core_item_energy_values: list[float] = []

        def _accumulate_attribute_bucket(*, attr_name: str, attr_er: float, attr_ev: float, owner_id: str) -> None:
            safe_name = str(attr_name or "").strip()
            if not safe_name:
                return
            bucket = bound_attribute_energy_totals.setdefault(
                safe_name,
                {
                    "attribute_name": safe_name,
                    "total_er": 0.0,
                    "total_ev": 0.0,
                    "total_energy": 0.0,
                    "item_count": 0,
                    "attribute_count": 0,
                },
            )
            bucket["total_er"] = round(float(bucket.get("total_er", 0.0)) + float(attr_er), 8)
            bucket["total_ev"] = round(float(bucket.get("total_ev", 0.0)) + float(attr_ev), 8)
            bucket["total_energy"] = round(float(bucket.get("total_er", 0.0)) + float(bucket.get("total_ev", 0.0)), 8)
            bucket["attribute_count"] = int(bucket.get("attribute_count", 0) or 0) + 1
            bucket.setdefault("_item_ids", set())
            if owner_id:
                bucket["_item_ids"].add(str(owner_id))

        for item in all_items:
            energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
            er = float(energy.get("er", 0.0) or 0.0)
            ev = float(energy.get("ev", 0.0) or 0.0)
            cp_abs = float(
                energy.get(
                    "cognitive_pressure_abs",
                    energy.get("cp_abs", 0.0),
                )
                or 0.0
            )
            if er >= 0.5:
                high_er_count += 1
            if ev >= 0.5:
                high_ev_count += 1
            if cp_abs >= 0.5:
                high_cp_count += 1
            total_er += er
            total_ev += ev
            total_cp += cp_abs
            total_energy = max(0.0, er) + max(0.0, ev)
            if total_energy > 1e-12:
                item_energy_values.append(total_energy)
                ref_type_key = str(item.get("ref_object_type", "") or "").strip().lower()
                if ref_type_key in {"st", "sg"} or (ref_type_key and ref_type_key not in {"em", "memory", "episodic_memory"}):
                    core_item_energy_values.append(total_energy)
            ref_type = item.get("ref_object_type", "unknown")
            type_counts[ref_type] = type_counts.get(ref_type, 0) + 1
            energy_bucket = energy_by_type.setdefault(
                ref_type,
                {
                    "count": 0,
                    "total_er": 0.0,
                    "total_ev": 0.0,
                    "total_cp": 0.0,
                },
            )
            energy_bucket["count"] += 1
            energy_bucket["total_er"] += er
            energy_bucket["total_ev"] += ev
            energy_bucket["total_cp"] += cp_abs
            context = self._context_metadata_fast(item)
            context_path_ids = context.get("context_path_ids", []) if isinstance(context, dict) else []
            has_context = bool(
                context.get("context_ref_object_id")
                or context.get("context_owner_structure_id")
                or context_path_ids
            )
            has_explicit_context = bool(
                context.get("context_ref_object_id")
                or context.get("context_owner_structure_id")
                or (isinstance(context_path_ids, list) and len(context_path_ids) > 1)
            )
            if has_context:
                contextual_item_count += 1
                depth = len(context_path_ids) if isinstance(context_path_ids, list) and context_path_ids else 1
                context_path_depth_total += depth
                if depth > 1:
                    multi_context_item_count += 1
            explicit_context = self._explicit_context_metadata_fast(item)
            explicit_context_path_ids = explicit_context.get("context_path_ids", []) if isinstance(explicit_context, dict) else []
            has_explicit_context = bool(
                explicit_context.get("context_ref_object_id")
                or explicit_context.get("context_owner_structure_id")
                or explicit_context_path_ids
            )
            if has_explicit_context:
                explicit_context_item_count += 1
                explicit_depth = (
                    len(explicit_context_path_ids)
                    if isinstance(explicit_context_path_ids, list) and explicit_context_path_ids
                    else 1
                )
                explicit_context_path_depth_total += explicit_depth
            residual = self._residual_metadata_fast(item)
            if residual.get("residual_origin_kind") or residual.get("residual_origin_entry_id"):
                residual_origin_item_count += 1
            meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
            runtime_resolution = meta_ext.get("runtime_resolution", {}) if isinstance(meta_ext.get("runtime_resolution", {}), dict) else {}
            if bool(runtime_resolution.get("is_degraded", False)):
                runtime_resolution_degraded_item_count += 1
            runtime_resolution_active_component_count += int(runtime_resolution.get("active_component_count", 0) or 0)
            runtime_resolution_dropped_component_count += int(runtime_resolution.get("dropped_component_count", 0) or 0)
            if item.get("binding_state", {}).get("bound_attribute_sa_ids"):
                bound_attribute_item_count += 1
            if item.get("sub_type") == "csa_binding_item":
                binding_csa_item_count += 1
            ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
            ref_attr_name = str(ref_snapshot.get("attribute_name", "") or "").strip()
            ref_role = str(ref_snapshot.get("role", "") or "").strip()
            if ref_role == "attribute" or ref_attr_name:
                _accumulate_attribute_bucket(
                    attr_name=ref_attr_name,
                    attr_er=er,
                    attr_ev=ev,
                    owner_id=str(item.get("id", "") or item.get("item_id", "") or ""),
                )

        attribute_energy_totals = {
            name: {
                **{k: v for k, v in row.items() if k != "_item_ids"},
                "item_count": len(row.get("_item_ids", set()) or set()),
            }
            for name, row in bound_attribute_energy_totals.items()
        }
        for bucket in energy_by_type.values():
            bucket["total_er"] = round(float(bucket.get("total_er", 0.0) or 0.0), 8)
            bucket["total_ev"] = round(float(bucket.get("total_ev", 0.0) or 0.0), 8)
            bucket["total_cp"] = round(float(bucket.get("total_cp", 0.0) or 0.0), 8)

        def _energy_shape(values: list[float]) -> tuple[float, float]:
            total = float(sum(max(0.0, float(value or 0.0)) for value in values))
            if total <= 1e-12:
                return 0.0, 0.0
            concentration = round(
                sum((max(0.0, float(value or 0.0)) / total) ** 2 for value in values if float(value or 0.0) > 1e-12),
                8,
            )
            effective_peak_count = round(1.0 / concentration, 8) if concentration > 1e-12 else 0.0
            return float(concentration), float(effective_peak_count)

        def _complexity_score(active_count: int, peak_count: float) -> float:
            size_norm = (float(active_count) - 6.0) / 18.0
            size_norm = max(0.0, min(1.0, size_norm))
            peak_norm = (float(peak_count) - 1.0) / 11.0
            peak_norm = max(0.0, min(1.0, peak_norm))
            return round(max(0.0, min(1.0, 0.55 * size_norm + 0.45 * peak_norm)), 8)

        energy_concentration, effective_peak_count = _energy_shape(item_energy_values)
        core_energy_concentration, core_effective_peak_count = _energy_shape(core_item_energy_values or item_energy_values)
        complexity_score = _complexity_score(len(all_items), effective_peak_count)
        core_complexity_score = _complexity_score(len(all_items), core_effective_peak_count)

        summary = {
            "active_item_count": len(all_items),
            "high_er_item_count": high_er_count,
            "high_ev_item_count": high_ev_count,
            "high_cp_item_count": high_cp_count,
            "total_er": round(total_er, 8),
            "total_ev": round(total_ev, 8),
            "total_energy": round(total_er + total_ev, 8),
            "total_cp": round(total_cp, 8),
            "object_type_counts": type_counts,
            "energy_by_type": energy_by_type,
            "pool": {
                "item_count": len(all_items),
                "active_item_count": len(all_items),
                "total_er": round(total_er, 8),
                "total_ev": round(total_ev, 8),
                "total_cp_abs": round(total_cp, 8),
                "energy_concentration": energy_concentration,
                "effective_peak_count": effective_peak_count,
                "complexity_score": complexity_score,
                "core_energy_concentration": core_energy_concentration,
                "core_effective_peak_count": core_effective_peak_count,
                "core_complexity_score": core_complexity_score,
            },
            "bound_attribute_item_count": bound_attribute_item_count,
            "binding_csa_item_count": binding_csa_item_count,
            "contextual_item_count": contextual_item_count,
            "explicit_context_item_count": explicit_context_item_count,
            "multi_context_item_count": multi_context_item_count,
            "context_path_depth_mean": round(float(context_path_depth_total) / float(contextual_item_count), 8) if contextual_item_count else 0.0,
            "explicit_context_path_depth_mean": round(float(explicit_context_path_depth_total) / float(explicit_context_item_count), 8) if explicit_context_item_count else 0.0,
            "residual_origin_item_count": residual_origin_item_count,
            "runtime_resolution_degraded_item_count": int(runtime_resolution_degraded_item_count),
            "runtime_resolution_active_component_count": int(runtime_resolution_active_component_count),
            "runtime_resolution_dropped_component_count": int(runtime_resolution_dropped_component_count),
            "attribute_energy_totals": attribute_energy_totals,
            "bound_attribute_energy_totals": dict(attribute_energy_totals),
        }
        if isinstance(runtime_stats, dict):
            injection_stats = runtime_stats.get("energy_injection_fatigue")
            if isinstance(injection_stats, dict):
                summary["energy_injection_fatigue"] = dict(injection_stats)

        # top items
        top_items = []
        er_top_items = []
        ev_top_items = []
        cp_top_items = []
        if include_items:
            sorted_items = pool_store.get_sorted(sort_by=sort_by, top_k=top_k)
            for item in sorted_items:
                top_items.append(self._build_top_item_summary(item))
            try:
                energy_top_k = int(self._config.get("snapshot_energy_top_k", 5) or 0)
            except Exception:
                energy_top_k = 5
            if energy_top_k > 0:
                def _energy_value(row: dict, key: str) -> float:
                    try:
                        energy = row.get("energy", {}) or {}
                        if key == "cp":
                            return float(
                                energy.get(
                                    "cognitive_pressure_abs",
                                    energy.get("cp_abs", 0.0),
                                )
                                or 0.0
                            )
                        return float(energy.get(key, 0.0) or 0.0)
                    except Exception:
                        return 0.0

                for item in heapq.nlargest(
                    energy_top_k,
                    all_items,
                    key=lambda row: _energy_value(row, "er"),
                ):
                    if _energy_value(item, "er") <= 0.0:
                        continue
                    er_top_items.append(self._build_top_item_summary(item))
                for item in heapq.nlargest(
                    energy_top_k,
                    all_items,
                    key=lambda row: _energy_value(row, "ev"),
                ):
                    if _energy_value(item, "ev") <= 0.0:
                        continue
                    ev_top_items.append(self._build_top_item_summary(item))
                for item in heapq.nlargest(
                    energy_top_k,
                    all_items,
                    key=lambda row: _energy_value(row, "cp"),
                ):
                    if _energy_value(item, "cp") <= 0.0:
                        continue
                    cp_top_items.append(self._build_top_item_summary(item))

        snapshot = {
            "snapshot_id": next_id("sps"),
            "object_type": "runtime_snapshot",
            "sub_type": "state_pool_snapshot",
            "schema_version": __schema_version__,
            "trace_id": trace_id,
            "tick_id": tick_id,
            "timestamp_ms": int(time.time() * 1000),
            "summary": summary,
            "top_items": top_items,
            "er_top_items": er_top_items,
            "ev_top_items": ev_top_items,
            "cp_top_items": cp_top_items,
        }

        if include_history_window and history_window:
            snapshot["history_window_ref"] = history_window.get_summary()

        return snapshot

    def build_script_check_packet(
        self,
        events: list[dict],
        pool_store,
        trace_id: str,
        tick_id: str = "",
    ) -> dict:
        """
        生成脚本检查抄送包。

        包含:
          - 本窗口事件列表
          - 变化统计
          - 候选触发摘要（认知压快速上升/下降的对象）
        """
        now_ms = int(time.time() * 1000)
        all_items = pool_store.get_all()

        # 事件起止时间
        window_start = events[0]["timestamp_ms"] if events else now_ms
        window_end = events[-1]["timestamp_ms"] if events else now_ms

        # 统计
        new_count = sum(1 for e in events if e.get("event_type") == "created")
        update_count = sum(1 for e in events if e.get("event_type") == "energy_update")

        # 候选触发
        fast_cp_rise = self._config.get("fast_cp_rise_threshold", 0.5)
        fast_cp_drop = self._config.get("fast_cp_drop_threshold", -0.5)
        candidates = []

        for item in all_items:
            d = item.get("dynamics", {})
            delta_cp_abs = d.get("delta_cp_abs", 0)
            if delta_cp_abs >= fast_cp_rise:
                candidates.append({
                    "item_id": item["id"],
                    "trigger_hint": "cp_abs_rise_fast",
                    "value": round(delta_cp_abs, 6),
                    "display": item.get("ref_snapshot", {}).get("content_display", ""),
                })
            elif delta_cp_abs <= fast_cp_drop:
                candidates.append({
                    "item_id": item["id"],
                    "trigger_hint": "cp_abs_drop_fast",
                    "value": round(delta_cp_abs, 6),
                    "display": item.get("ref_snapshot", {}).get("content_display", ""),
                })

        high_cp_count = sum(1 for i in all_items if i["energy"]["cognitive_pressure_abs"] >= 0.5)
        fast_rise_count = sum(1 for c in candidates if c["trigger_hint"] == "cp_abs_rise_fast")
        fast_drop_count = sum(1 for c in candidates if c["trigger_hint"] == "cp_abs_drop_fast")

        packet = {
            "packet_id": next_id("scp"),
            "object_type": "runtime_snapshot",
            "sub_type": "state_change_window_packet",
            "schema_version": __schema_version__,
            "trace_id": trace_id,
            "tick_id": tick_id,
            "window_start_ms": window_start,
            "window_end_ms": window_end,
            "summary": {
                "active_item_count": len(all_items),
                "new_item_count": new_count,
                "updated_item_count": update_count,
                "high_cp_item_count": high_cp_count,
                "fast_cp_rise_item_count": fast_rise_count,
                "fast_cp_drop_item_count": fast_drop_count,
            },
            "candidate_triggers": candidates,
        }

        # 包含完整事件列表（可配置）
        if self._config.get("script_broadcast_include_full_event_dump", True):
            packet["events"] = events
        else:
            packet["event_count"] = len(events)

        return packet

    def build_attention_snapshot(
        self,
        pool_store,
        trace_id: str,
        tick_id: str = "",
        top_k: int = 64,
    ) -> dict:
        """生成供注意力过滤器使用的摘要快照。"""
        sorted_items = pool_store.get_sorted(sort_by="cp_abs", top_k=top_k)
        items_summary = []
        for item in sorted_items:
            items_summary.append({
                "item_id": item["id"],
                "ref_object_id": item.get("ref_object_id", ""),
                "ref_object_type": item.get("ref_object_type", ""),
                "display": item.get("ref_snapshot", {}).get("content_display", ""),
                "er": item["energy"]["er"],
                "ev": item["energy"]["ev"],
                "cp_abs": item["energy"]["cognitive_pressure_abs"],
                "salience": item["energy"].get("salience_score", 0),
            })
        return {
            "snapshot_type": "attention_input",
            "trace_id": trace_id,
            "tick_id": tick_id,
            "total_pool_size": pool_store.size,
            "top_k": top_k,
            "items": items_summary,
        }

    def update_config(self, config: dict):
        self._config = config
        if not bool(self._config.get("enable_snapshot_item_summary_cache", True)):
            self.clear_item_summary_cache()

    def clear_item_summary_cache(self) -> None:
        self._item_summary_cache.clear()
        self._item_summary_cache_order.clear()

    def _item_summary_cache_key(self, item: dict) -> tuple:
        ref_snapshot = item.get("ref_snapshot", {}) if isinstance(item.get("ref_snapshot", {}), dict) else {}
        energy = item.get("energy", {}) if isinstance(item.get("energy", {}), dict) else {}
        dynamics = item.get("dynamics", {}) if isinstance(item.get("dynamics", {}), dict) else {}
        binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
        ext = item.get("ext", {}) if isinstance(item.get("ext", {}), dict) else {}
        meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
        runtime_resolution = meta_ext.get("runtime_resolution", {}) if isinstance(meta_ext.get("runtime_resolution", {}), dict) else {}
        bound_attrs = ext.get("bound_attributes", []) if isinstance(ext.get("bound_attributes", []), list) else []
        attr_energy_sig = []
        for attr in bound_attrs:
            if not isinstance(attr, dict):
                continue
            content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
            attr_energy = attr.get("energy", {}) if isinstance(attr.get("energy", {}), dict) else {}
            attr_energy_sig.append(
                (
                    str(attr.get("id", "") or ""),
                    str(content.get("attribute_name", "") or content.get("raw", "") or ""),
                    content.get("attribute_value", None),
                    attr_energy.get("er", 0.0),
                    attr_energy.get("ev", 0.0),
                    int(attr.get("updated_at", 0) or 0),
                )
            )
        packet_by_name = binding_state.get("packet_attribute_by_name", {})
        runtime_by_name = binding_state.get("bound_attribute_by_name", {})
        return (
            str(item.get("id", "") or ""),
            str(item.get("ref_object_id", "") or ""),
            str(item.get("ref_object_type", "") or ""),
            str(item.get("semantic_signature", "") or ""),
            int(item.get("updated_at", 0) or 0),
            str(item.get("status", "") or ""),
            energy.get("er", 0.0),
            energy.get("ev", 0.0),
            energy.get("cognitive_pressure_delta", 0.0),
            energy.get("cognitive_pressure_abs", 0.0),
            energy.get("salience_score", 0.0),
            energy.get("fatigue", 0.0),
            energy.get("recency_gain", 0.0),
            tuple(sorted((energy.get("injection_fatigue", {}) or {}).items())) if isinstance(energy.get("injection_fatigue", {}), dict) else (),
            dynamics.get("delta_er", 0.0),
            dynamics.get("delta_ev", 0.0),
            dynamics.get("delta_cp_delta", 0.0),
            dynamics.get("delta_cp_abs", 0.0),
            dynamics.get("update_count", 0),
            tuple(binding_state.get("bound_attribute_sa_ids", []) or []),
            tuple(sorted(str(k) for k in packet_by_name.keys())) if isinstance(packet_by_name, dict) else (),
            tuple(sorted(str(k) for k in runtime_by_name.keys())) if isinstance(runtime_by_name, dict) else (),
            tuple(attr_energy_sig),
            str(runtime_resolution.get("root_structure_id", "") or ""),
            runtime_resolution.get("resolution_ratio", 1.0),
            runtime_resolution.get("active_component_count", 0),
            runtime_resolution.get("dropped_component_count", 0),
            bool(runtime_resolution.get("is_degraded", False)),
            str(ref_snapshot.get("content_signature", "") or ""),
            str(ref_snapshot.get("content_display", "") or ""),
            int(ref_snapshot.get("token_count", 0) or ref_snapshot.get("member_count", 0) or 0),
            len(ref_snapshot.get("flat_tokens", []) or []) if isinstance(ref_snapshot.get("flat_tokens", []), list) else 0,
            len(ref_snapshot.get("sequence_groups", []) or []) if isinstance(ref_snapshot.get("sequence_groups", []), list) else 0,
            len(ref_snapshot.get("member_refs", []) or []) if isinstance(ref_snapshot.get("member_refs", []), list) else 0,
        )

    def _copy_item_summary(self, summary: dict) -> dict:
        copy_mode = str(self._config.get("snapshot_item_summary_copy_mode", "shallow") or "shallow").strip().lower()
        if copy_mode != "deep":
            copied = dict(summary)
            ref_snapshot = copied.get("ref_snapshot", {})
            if isinstance(ref_snapshot, dict):
                copied["ref_snapshot"] = dict(ref_snapshot)
            return copied
        copied = dict(summary)
        for key in (
            "ref_alias_ids",
            "attribute_displays",
            "feature_displays",
            "bound_attribute_displays",
            "runtime_bound_attribute_units",
            "packet_attribute_names",
            "runtime_attribute_names",
            "all_attribute_names",
            "bound_attribute_names",
            "context_path_ids",
            "component_energy",
        ):
            if isinstance(copied.get(key), list):
                copied[key] = list(copied.get(key) or [])
        ref_snapshot = copied.get("ref_snapshot", {})
        if isinstance(ref_snapshot, dict):
            ref_copy = dict(ref_snapshot)
            for key in (
                "flat_tokens",
                "sequence_groups",
                "member_refs",
                "attribute_displays",
                "feature_displays",
                "bound_attribute_displays",
                "runtime_bound_attribute_units",
            ):
                if isinstance(ref_copy.get(key), list):
                    ref_copy[key] = list(ref_copy.get(key) or [])
            copied["ref_snapshot"] = ref_copy
        return copied

    def _remember_item_summary(self, key: tuple, summary: dict) -> None:
        if not bool(self._config.get("enable_snapshot_item_summary_cache", True)):
            return
        try:
            max_entries = int(self._config.get("snapshot_item_summary_cache_max_entries", 8192) or 8192)
        except Exception:
            max_entries = 8192
        if max_entries <= 0:
            return
        self._item_summary_cache[key] = self._copy_item_summary(summary)
        self._item_summary_cache_order.append(key)
        while len(self._item_summary_cache_order) > max_entries:
            old_key = self._item_summary_cache_order.pop(0)
            if old_key != key:
                self._item_summary_cache.pop(old_key, None)

    def _build_top_item_summary(self, item: dict) -> dict:
        """构建适合调试、测试和交互演示的状态池项摘要。"""
        cache_key = None
        if bool(self._config.get("enable_snapshot_item_summary_cache", True)):
            try:
                cache_key = self._item_summary_cache_key(item)
                cached = self._item_summary_cache.get(cache_key)
                if isinstance(cached, dict):
                    return self._copy_item_summary(cached)
            except Exception:
                cache_key = None
        ref_snapshot = item.get("ref_snapshot", {})
        energy = item.get("energy", {})
        dynamics = item.get("dynamics", {})
        binding_state = item.get("binding_state", {})

        # Extract time-feeling bucket meta (best-effort) for rules/actions.
        # 从绑定属性中提取“时间感受”的桶元信息（尽力而为），供 IESM/行动参数透传使用：
        # - 避免必须把时间桶节点常驻入池才能拿到时间间隔参数（对齐理论 4.2.6~4.2.7）。
        time_bucket_ref_object_id = ""
        time_bucket_id = ""
        time_bucket_label_zh = ""
        time_bucket_unit = ""
        time_basis = ""
        time_bucket_center_sec: float | None = None
        try:
            for attr in item.get("ext", {}).get("bound_attributes", []) or []:
                if not isinstance(attr, dict):
                    continue
                content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
                attr_name = str(content.get("attribute_name", "") or "").strip()
                if not attr_name:
                    raw = str(content.get("raw", "") or "")
                    if ":" in raw:
                        attr_name = raw.split(":", 1)[0].strip()
                if attr_name != "时间感受":
                    continue
                ext_meta = attr.get("meta", {}).get("ext", {}) if isinstance(attr.get("meta", {}).get("ext", {}), dict) else {}
                time_bucket_ref_object_id = str(ext_meta.get("time_bucket_ref_object_id", "") or "").strip()
                time_bucket_id = str(ext_meta.get("time_bucket_id", "") or "").strip()
                time_bucket_label_zh = str(ext_meta.get("time_bucket_label_zh", "") or "").strip()
                time_bucket_unit = str(ext_meta.get("time_bucket_unit", "") or "").strip()
                time_basis = str(ext_meta.get("time_basis", "") or "").strip()
                try:
                    if ext_meta.get("time_bucket_center_sec", None) is not None:
                        time_bucket_center_sec = float(ext_meta.get("time_bucket_center_sec"))
                except Exception:
                    time_bucket_center_sec = None
                break
        except Exception:
            time_bucket_ref_object_id = ""
            time_bucket_id = ""
            time_bucket_label_zh = ""
            time_bucket_unit = ""
            time_basis = ""
            time_bucket_center_sec = None

        bound_attributes = [
            attr.get("content", {}).get("display", attr.get("content", {}).get("raw", attr.get("id", "")))
            for attr in item.get("ext", {}).get("bound_attributes", [])
            if isinstance(attr, dict)
        ]
        runtime_bound_attribute_units: list[dict] = []
        for attr in item.get("ext", {}).get("bound_attributes", []) or []:
            if not isinstance(attr, dict):
                continue
            content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
            meta = attr.get("meta", {}) if isinstance(attr.get("meta", {}), dict) else {}
            ext_meta = meta.get("ext", {}) if isinstance(meta.get("ext", {}), dict) else {}
            attr_name = str(content.get("attribute_name", "") or "").strip()
            attr_raw = str(content.get("raw", "") or "").strip()
            attr_display = str(content.get("display", "") or attr_raw or attr.get("id", "")).strip()
            attr_value = content.get("attribute_value", None)
            if not attr_name and ":" in attr_raw:
                attr_name = attr_raw.split(":", 1)[0].strip()
            if not attr_name and attr_value in ("", None):
                continue
            runtime_bound_attribute_units.append(
                {
                    "attribute_name": attr_name,
                    "attribute_value": attr_value,
                    "value_type": str(content.get("value_type", "") or "").strip(),
                    "raw": attr_raw,
                    "display": attr_display,
                    "meta": {
                        "ext": {
                            key: ext_meta.get(key)
                            for key in (
                                "time_bucket_id",
                                "time_bucket_ref_object_id",
                                "time_bucket_center_sec",
                                "time_bucket_center_value",
                                "time_bucket_secondary_id",
                                "time_bucket_secondary_center_sec",
                                "time_bucket_secondary_center_value",
                                "time_basis",
                                "time_unit",
                                "delta_sec",
                                "delta_value",
                            )
                            if key in ext_meta
                        }
                    },
                }
            )
        # attribute_names（属性名稳定键）
        # ------------------------------------------------
        # 理论对齐点：
        # - CFS（认知感受信号）、奖励/惩罚、时间感受等都应作为“属性刺激元（attribute SA）”进入系统匹配与记忆闭环。
        #
        # 工程对齐点：
        # - 目前属性有两条入口：
        #   1) packet 属性（来自感受器/回忆反哺 stimulus_packet）：binding_state.packet_attribute_by_name
        #   2) runtime 绑定属性（来自 IESM/time_sensor 等运行态绑定）：binding_state.bound_attribute_by_name / ext.bound_attributes
        #
        # 这三组字段的用途：
        # - packet_attribute_names: 用于检视“记忆/结构侧”属性是否真正进入刺激流与结构形成（验收要求）。
        # - runtime_attribute_names: 用于检视“运行态绑定”是否生效（IESM/时间感受器等）。
        # - all_attribute_names: 规则引擎与前端推荐使用的统一口径（避免仅靠 display contains_text 导致易碎）。
        binding_state = item.get("binding_state", {}) if isinstance(item.get("binding_state", {}), dict) else {}
        packet_by_name = binding_state.get("packet_attribute_by_name", {})
        packet_attribute_names = (
            sorted([str(k) for k in packet_by_name.keys() if str(k)]) if isinstance(packet_by_name, dict) else []
        )
        runtime_by_name = binding_state.get("bound_attribute_by_name", {})
        runtime_attribute_names = (
            sorted([str(k) for k in runtime_by_name.keys() if str(k)]) if isinstance(runtime_by_name, dict) else []
        )
        self_attribute_name = str(ref_snapshot.get("attribute_name", "") or "").strip()

        # Backward-compatible fallback: ext.bound_attributes -> runtime_attribute_names
        # 兼容兜底：如果没有 bound_attribute_by_name，则从 ext.bound_attributes 推断 runtime 属性名。
        if not runtime_attribute_names:
            inferred: list[str] = []
            for attr in item.get("ext", {}).get("bound_attributes", []) or []:
                if not isinstance(attr, dict):
                    continue
                content = attr.get("content", {}) if isinstance(attr.get("content", {}), dict) else {}
                name = str(content.get("attribute_name", "") or "").strip()
                if not name:
                    raw = str(content.get("raw", "") or "")
                    if ":" in raw:
                        name = raw.split(":", 1)[0].strip()
                    else:
                        name = raw.strip()
                if name:
                    inferred.append(name)
            runtime_attribute_names = sorted(set(inferred))

        # all_attribute_names: union (dedupe, keep stable order: packet -> runtime)
        seen_names: set[str] = set()
        all_attribute_names: list[str] = []
        for name in [*packet_attribute_names, *runtime_attribute_names, *([self_attribute_name] if self_attribute_name else [])]:
            if not name or name in seen_names:
                continue
            seen_names.add(name)
            all_attribute_names.append(name)

        # Backward compatibility: keep existing field name for older UI/logic.
        # 向后兼容：保留历史字段 bound_attribute_names（旧 UI/逻辑仍可能读取）。
        bound_attribute_names = list(runtime_attribute_names)

        lightweight_ref_snapshot = {
            "content_display": ref_snapshot.get("content_display", ""),
            "content_display_detail": ref_snapshot.get("content_display_detail", ""),
            "content_signature": ref_snapshot.get("content_signature", ""),
            "token_count": int(ref_snapshot.get("token_count", len(ref_snapshot.get("flat_tokens", []) or [])) or ref_snapshot.get("member_count", 0) or 0),
            "member_count": ref_snapshot.get("member_count", 0),
            "flat_tokens": list(ref_snapshot.get("flat_tokens", []) or []),
            "sequence_groups": list(ref_snapshot.get("sequence_groups", []) or []),
            "member_refs": list(ref_snapshot.get("member_refs", []) or []),
        }
        for key in (
            "role",
            "attribute_name",
            "attribute_value",
            "value_type",
            "context_ref_object_id",
            "context_ref_object_type",
            "context_owner_id",
            "context_text",
            "residual_kind",
            "source_em_id",
            "memory_id",
            "source_memory_created_at",
            "action_id",
            "action_kind",
            "target_ref_object_id",
            "target_ref_object_type",
            "target_item_id",
            "target_display",
            "drive_hint",
            "consumed_drive_hint",
            "effective_threshold",
            "threshold_scale",
        ):
            value = ref_snapshot.get(key, None)
            if value not in ("", None, [], {}):
                lightweight_ref_snapshot[key] = value
        if ref_snapshot.get("anchor_display"):
            lightweight_ref_snapshot["anchor_display"] = ref_snapshot.get("anchor_display", "")
        if ref_snapshot.get("attribute_displays"):
            lightweight_ref_snapshot["attribute_displays"] = list(ref_snapshot.get("attribute_displays", []) or [])
        if ref_snapshot.get("feature_displays"):
            lightweight_ref_snapshot["feature_displays"] = list(ref_snapshot.get("feature_displays", []) or [])
        if runtime_bound_attribute_units:
            lightweight_ref_snapshot["runtime_bound_attribute_units"] = [dict(unit) for unit in runtime_bound_attribute_units]
        if ref_snapshot.get("bound_attribute_displays"):
            lightweight_ref_snapshot["bound_attribute_displays"] = list(ref_snapshot.get("bound_attribute_displays", []) or [])
        if ref_snapshot.get("structure_ext"):
            lightweight_ref_snapshot["structure_ext"] = ref_snapshot.get("structure_ext", {})
        if ref_snapshot.get("group_ext"):
            lightweight_ref_snapshot["group_ext"] = ref_snapshot.get("group_ext", {})

        structure_ext = ref_snapshot.get("structure_ext", {}) if isinstance(ref_snapshot.get("structure_ext", {}), dict) else {}
        structure_sequence_mode = str(structure_ext.get("sequence_mode", "") or "").strip()
        context_meta = self._context_metadata_fast(item)
        residual_meta = self._residual_metadata_fast(item)
        meta_ext = item.get("meta", {}).get("ext", {}) if isinstance(item.get("meta", {}).get("ext", {}), dict) else {}
        runtime_resolution = meta_ext.get("runtime_resolution", {}) if isinstance(meta_ext.get("runtime_resolution", {}), dict) else {}
        component_energy = meta_ext.get("component_energy", {}) if isinstance(meta_ext.get("component_energy", {}), dict) else {}
        groups = ref_snapshot.get("sequence_groups", []) if isinstance(ref_snapshot.get("sequence_groups", []), list) else []
        has_goal_b_string_group = False
        has_non_string_group = False
        for group in groups:
            if not isinstance(group, dict):
                continue
            is_goal_b_string = bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence"
            if is_goal_b_string:
                has_goal_b_string_group = True
            else:
                tokens = [str(token) for token in (group.get("tokens", []) or []) if str(token)]
                if tokens:
                    has_non_string_group = True
        goal_b_mixed_structure = bool(has_goal_b_string_group and has_non_string_group)

        summary = {
            "item_id": item["id"],
            "ref_object_id": item.get("ref_object_id", ""),
            "ref_object_type": item.get("ref_object_type", ""),
            # ref_alias_ids: 同一“语义对象”在不同模块/阶段可能拥有不同 ref_id（例如 sa_* 与 st_*）。
            # 在状态池里它们会被语义合并为同一运行态对象；为保证观测台与规则引擎能正确解析目标对象，
            # 这里显式输出别名列表，避免前端只剩 st_000xxx 这种 ID 看不到内容的问题。
            #
            # ref_alias_ids: one semantic object may have multiple ref ids across modules/phases
            # (e.g. sa_* and st_*). We expose aliases for UI resolution and rule-engine targeting.
            "ref_alias_ids": list(item.get("ref_alias_ids", []) or []),
            "display": ref_snapshot.get("content_display", ""),
            "display_text": ref_snapshot.get("content_display", ""),
            "display_detail": self._build_display_detail(item, bound_attributes),
            "anchor_display": ref_snapshot.get("anchor_display", ""),
            "role": ref_snapshot.get("role", ""),
            "attribute_name": ref_snapshot.get("attribute_name", ""),
            "attribute_value": ref_snapshot.get("attribute_value", None),
            "value_type": ref_snapshot.get("value_type", ""),
            "ref_snapshot": lightweight_ref_snapshot,
            "semantic_signature": str(item.get("semantic_signature", "") or ""),
            "semantic_context_key": str(item.get("semantic_context_key", "") or ""),
            "runtime_root_structure_id": str(runtime_resolution.get("root_structure_id", item.get("ext", {}).get("runtime_root_structure_id", "")) or ""),
            "runtime_resolution_ratio": runtime_resolution.get("resolution_ratio", 1.0),
            "runtime_resolution_degraded": bool(runtime_resolution.get("is_degraded", False)),
            "runtime_resolution_active_component_count": int(runtime_resolution.get("active_component_count", 0) or 0),
            "runtime_resolution_dropped_component_count": int(runtime_resolution.get("dropped_component_count", 0) or 0),
            "component_energy": dict(component_energy),
            "structure_sequence_mode": structure_sequence_mode,
            "goal_b_mixed_structure": goal_b_mixed_structure,
            "context_ref_object_id": context_meta.get("context_ref_object_id", ""),
            "context_ref_object_type": context_meta.get("context_ref_object_type", ""),
            "context_owner_structure_id": context_meta.get("context_owner_structure_id", ""),
            "context_owner_id": ref_snapshot.get("context_owner_id", context_meta.get("context_owner_structure_id", "")),
            "context_path_ids": list(context_meta.get("context_path_ids", [])),
            "context_explicit": bool(ref_snapshot.get("context_explicit", False)),
            "context_text": ref_snapshot.get("context_text", ""),
            "action_id": ref_snapshot.get("action_id", ""),
            "action_kind": ref_snapshot.get("action_kind", ref_snapshot.get("action_type", "")),
            "target_ref_object_id": ref_snapshot.get("target_ref_object_id", ""),
            "target_ref_object_type": ref_snapshot.get("target_ref_object_type", ""),
            "target_item_id": ref_snapshot.get("target_item_id", ""),
            "target_display": ref_snapshot.get("target_display", ""),
            "residual_origin_kind": residual_meta.get("residual_origin_kind", ""),
            "residual_origin_entry_id": residual_meta.get("residual_origin_entry_id", ""),
            "residual_kind": ref_snapshot.get("residual_kind", ""),
            "source_em_id": ref_snapshot.get("source_em_id", ""),
            "memory_id": ref_snapshot.get("memory_id", ""),
            "source_memory_created_at": ref_snapshot.get("source_memory_created_at", 0),
            "attribute_displays": list(ref_snapshot.get("attribute_displays", [])),
            # feature_displays / 特征展示（例如 CSA 的非属性成员摘要）
            # 用途：先天规则 metric 选择器 contains_text 可用来匹配“包含某特征”的对象。
            "feature_displays": list(ref_snapshot.get("feature_displays", [])),
            "bound_attribute_displays": list(ref_snapshot.get("bound_attribute_displays", [])),
            "runtime_bound_attribute_units": [dict(unit) for unit in runtime_bound_attribute_units],
            # time_bucket_*: 时间桶元信息（仅当存在“时间感受”绑定属性时才有值）
            "time_bucket_ref_object_id": time_bucket_ref_object_id,
            "time_bucket_id": time_bucket_id,
            "time_bucket_label_zh": time_bucket_label_zh,
            "time_bucket_unit": time_bucket_unit,
            "time_basis": time_basis,
            "time_bucket_center_sec": time_bucket_center_sec,
            # packet_attribute_names: packet 属性名（来自刺激包/回忆反哺）
            "packet_attribute_names": list(packet_attribute_names),
            # runtime_attribute_names: 运行态绑定属性名（来自 IESM/time_sensor 等）
            "runtime_attribute_names": list(runtime_attribute_names),
            # all_attribute_names: 推荐规则引擎/前端统一口径
            "all_attribute_names": list(all_attribute_names),
            "bound_attribute_names": list(bound_attribute_names),
            "member_count": ref_snapshot.get("member_count", 0),
            "er": energy.get("er", 0),
            "ev": energy.get("ev", 0),
            "cp_delta": energy.get("cognitive_pressure_delta", 0),
            "cp_abs": energy.get("cognitive_pressure_abs", 0),
            "salience_score": energy.get("salience_score", 0),
            "fatigue": energy.get("fatigue", 0),
            "recency_gain": energy.get("recency_gain", 0),
            "energy_injection_fatigue": dict(energy.get("injection_fatigue", {}) or {}) if isinstance(energy.get("injection_fatigue", {}), dict) else {},
            "delta_er": dynamics.get("delta_er", 0),
            "delta_ev": dynamics.get("delta_ev", 0),
            # 说明：
            # - delta_cp_delta / cp_delta_rate 在能量引擎里会更新，但旧版摘要里没暴露；
            # - IESM 的 metric 条件（获得认知压/变化率）会用到它们作为早期 tick 的 fallback。
            "delta_cp_delta": dynamics.get("delta_cp_delta", 0),
            "delta_cp_abs": dynamics.get("delta_cp_abs", 0),
            "er_change_rate": dynamics.get("er_change_rate", 0),
            "ev_change_rate": dynamics.get("ev_change_rate", 0),
            "cp_delta_rate": dynamics.get("cp_delta_rate", 0),
            "cp_abs_rate": dynamics.get("cp_abs_rate", 0),
            "update_count": dynamics.get("update_count", 0),
            "last_update_tick": dynamics.get("last_update_tick", 0),
            "bound_attribute_count": len(binding_state.get("bound_attribute_sa_ids", [])),
            "bound_csa_item_id": binding_state.get("bound_csa_item_id"),
            "status": item.get("status", "active"),
            "updated_at": item.get("updated_at", 0),
            "created_at": item.get("created_at", 0),
        }
        if cache_key is not None:
            self._remember_item_summary(cache_key, summary)
        return self._copy_item_summary(summary)

    def _build_display_detail(self, item: dict, bound_attributes: list[str]) -> str:
        """生成适合交互演示的人类可读解释摘要。"""
        ref_snapshot = item.get("ref_snapshot", {})
        detail = ref_snapshot.get("content_display_detail")
        if detail:
            return detail

        parts = []
        if ref_snapshot.get("anchor_display"):
            parts.append(f"anchor={ref_snapshot.get('anchor_display')}")
        if ref_snapshot.get("attribute_displays"):
            parts.append(f"attrs={', '.join(ref_snapshot.get('attribute_displays', [])[:4])}")
        if bound_attributes:
            parts.append(f"runtime_attrs={', '.join(bound_attributes[:4])}")
        if ref_snapshot.get("member_count"):
            parts.append(f"members={ref_snapshot.get('member_count')}")
        context_meta = self._context_metadata_fast(item)
        if context_meta.get("context_owner_structure_id"):
            parts.append(f"上下文owner={context_meta.get('context_owner_structure_id')}")
        elif context_meta.get("context_ref_object_id"):
            parts.append(f"上下文ref={context_meta.get('context_ref_object_id')}")
        path_ids = context_meta.get("context_path_ids", []) if isinstance(context_meta.get("context_path_ids", []), list) else []
        depth = len(path_ids) if path_ids else (1 if (context_meta.get("context_ref_object_id") or context_meta.get("context_owner_structure_id")) else 0)
        if depth > 1:
            parts.append(f"路径深度={depth}")
        residual_meta = self._residual_metadata_fast(item)
        if residual_meta.get("residual_origin_kind"):
            parts.append(f"残差来源={residual_meta.get('residual_origin_kind')}")
        return " | ".join(parts)



