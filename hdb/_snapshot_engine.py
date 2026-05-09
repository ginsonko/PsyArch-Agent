# -*- coding: utf-8 -*-
"""
Snapshot exporter for HDB.
"""

from __future__ import annotations

import time

from ._context_metadata import (
    context_path_depth,
    extract_context_metadata,
    extract_residual_metadata,
    has_context_metadata,
    has_residual_metadata,
)
from ._id_generator import next_id


class SnapshotEngine:
    def __init__(self, config: dict):
        self._config = config

    def update_config(self, config: dict) -> None:
        self._config = config

    def build_hdb_snapshot(
        self,
        *,
        trace_id: str,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        pointer_index,
        issue_queue: list[dict],
        repair_jobs: dict[str, dict],
        top_k: int = 10,
        include_stats: bool = True,
        include_recent_structures: bool = True,
        include_recent_groups: bool = True,
    ) -> dict:
        active_jobs = [job for job in repair_jobs.values() if job.get("status") in {"running", "pending", "stopping"}]
        memory_activation_items = list(memory_activation_store.iter_items())
        memory_activation_total_er = round(
            sum(float(item.get("er", 0.0)) for item in memory_activation_items),
            8,
        )
        memory_activation_total_ev = round(
            sum(float(item.get("ev", 0.0)) for item in memory_activation_items),
            8,
        )
        runtime_context_summary = {}
        summary_getter = getattr(structure_store, "get_runtime_context_summary", None)
        if callable(summary_getter):
            try:
                runtime_context_summary = summary_getter()
            except Exception:
                runtime_context_summary = {}
        if not isinstance(runtime_context_summary, dict) or not runtime_context_summary:
            structures = list(structure_store.iter_structures())
            structure_dbs = list(structure_store.iter_structure_dbs())
            contextual_structure_count = 0
            multi_context_structure_count = 0
            structure_context_path_depth_total = 0
            signature_context_pairs: dict[str, set[str]] = {}
            for structure in structures:
                if has_context_metadata(structure):
                    contextual_structure_count += 1
                    depth = context_path_depth(structure)
                    structure_context_path_depth_total += depth
                    if depth > 1:
                        multi_context_structure_count += 1
                context_meta = extract_context_metadata(structure)
                signature = str(structure.get("structure", {}).get("content_signature", "") or "").strip()
                context_key = str(
                    context_meta.get("context_owner_structure_id")
                    or context_meta.get("context_ref_object_id")
                    or ""
                ).strip()
                if signature and context_key:
                    signature_context_pairs.setdefault(signature, set()).add(context_key)
            same_content_multi_context_count = sum(
                1 for contexts in signature_context_pairs.values()
                if len(contexts) > 1
            )
            diff_entry_count = 0
            contextual_diff_entry_count = 0
            residual_diff_entry_count = 0
            diff_entry_with_memory_ref_count = 0
            for structure_db in structure_dbs:
                owner_structure_id = str(structure_db.get("owner_structure_id", "") or "")
                for entry in list(structure_db.get("diff_table", []) or []):
                    if not isinstance(entry, dict):
                        continue
                    diff_entry_count += 1
                    if entry.get("memory_refs"):
                        diff_entry_with_memory_ref_count += 1
                    if self._is_contextual_diff_entry(entry, owner_structure_id=owner_structure_id):
                        contextual_diff_entry_count += 1
                    if self._is_residual_local_diff_entry(entry):
                        residual_diff_entry_count += 1
            runtime_context_summary = {
                "contextual_structure_count": contextual_structure_count,
                "multi_context_structure_count": multi_context_structure_count,
                "structure_context_path_depth_mean": round(float(structure_context_path_depth_total) / float(contextual_structure_count), 8) if contextual_structure_count else 0.0,
                "same_content_multi_context_count": same_content_multi_context_count,
                "diff_entry_count": diff_entry_count,
                "contextual_diff_entry_count": contextual_diff_entry_count,
                "residual_diff_entry_count": residual_diff_entry_count,
                "diff_entry_with_memory_ref_count": diff_entry_with_memory_ref_count,
            }
        snapshot = {
            "snapshot_id": next_id("hdbs"),
            "object_type": "runtime_snapshot",
            "sub_type": "hdb_snapshot",
            "trace_id": trace_id,
            "timestamp_ms": int(time.time() * 1000),
            "summary": {
                "structure_count": structure_store.structure_count,
                "structure_db_count": structure_store.structure_db_count,
                "group_count": group_store.size,
                "episodic_count": episodic_store.size,
                "memory_activation_count": memory_activation_store.size,
                "memory_activation_total_er": memory_activation_total_er,
                "memory_activation_total_ev": memory_activation_total_ev,
                "memory_activation_total_energy": round(memory_activation_total_er + memory_activation_total_ev, 8),
                "issue_count": len(issue_queue),
                "active_repair_job_count": len(active_jobs),
                "contextual_structure_count": int(runtime_context_summary.get("contextual_structure_count", 0) or 0),
                "multi_context_structure_count": int(runtime_context_summary.get("multi_context_structure_count", 0) or 0),
                "structure_context_path_depth_mean": round(float(runtime_context_summary.get("structure_context_path_depth_mean", 0.0) or 0.0), 8),
                "same_content_multi_context_count": int(runtime_context_summary.get("same_content_multi_context_count", 0) or 0),
                "diff_entry_count": int(runtime_context_summary.get("diff_entry_count", 0) or 0),
                "contextual_diff_entry_count": int(runtime_context_summary.get("contextual_diff_entry_count", 0) or 0),
                "residual_diff_entry_count": int(runtime_context_summary.get("residual_diff_entry_count", 0) or 0),
                "diff_entry_with_memory_ref_count": int(runtime_context_summary.get("diff_entry_with_memory_ref_count", 0) or 0),
            },
        }
        if include_stats:
            snapshot["stats"] = {
                "pointer_index": pointer_index.export_snapshot(),
                "recent_issue_types": self._summarize_issue_types(issue_queue),
            }
        if include_recent_structures:
            snapshot["recent_structures"] = [
                {
                    "structure_id": item.get("id", ""),
                    "display_text": item.get("structure", {}).get("display_text", ""),
                    "signature": item.get("structure", {}).get("content_signature", ""),
                    "context_ref_object_id": extract_context_metadata(item).get("context_ref_object_id", ""),
                    "context_ref_object_type": extract_context_metadata(item).get("context_ref_object_type", ""),
                    "context_owner_structure_id": extract_context_metadata(item).get("context_owner_structure_id", ""),
                    "context_path_ids": list(extract_context_metadata(item).get("context_path_ids", [])),
                    "base_weight": item.get("stats", {}).get("base_weight", 0.0),
                    "recent_gain": item.get("stats", {}).get("recent_gain", 1.0),
                    "fatigue": item.get("stats", {}).get("fatigue", 0.0),
                    "created_at": item.get("created_at", 0),
                }
                for item in structure_store.get_recent_structures(limit=top_k)
            ]
        if include_recent_groups:
            snapshot["recent_groups"] = [
                {
                    "group_id": item.get("id", ""),
                    "required_structure_ids": list(item.get("required_structure_ids", [])),
                    "required_structures": self._resolve_structure_refs(
                        structure_store,
                        item.get("required_structure_ids", []),
                    ),
                    "bias_structure_ids": list(item.get("bias_structure_ids", [])),
                    "bias_structures": self._resolve_structure_refs(
                        structure_store,
                        item.get("bias_structure_ids", []),
                    ),
                    "avg_energy_profile": dict(item.get("avg_energy_profile", {})),
                    "base_weight": item.get("stats", {}).get("base_weight", 0.0),
                    "recent_gain": item.get("stats", {}).get("recent_gain", 1.0),
                    "fatigue": item.get("stats", {}).get("fatigue", 0.0),
                    "created_at": item.get("created_at", 0),
                }
                for item in group_store.get_recent(limit=top_k)
            ]
        snapshot["recent_episodic"] = [
            {
                "episodic_id": item.get("id", ""),
                "event_summary": item.get("event_summary", ""),
                "structure_refs": list(item.get("structure_refs", [])),
                "structure_ref_items": self._resolve_structure_refs(
                    structure_store,
                    item.get("structure_refs", []),
                ),
                "group_refs": list(item.get("group_refs", [])),
                "group_ref_items": self._resolve_group_refs(
                    group_store,
                    structure_store,
                    item.get("group_refs", []),
                ),
                "created_at": item.get("created_at", 0),
            }
            for item in episodic_store.get_recent(limit=top_k)
        ]
        snapshot["recent_memory_activations"] = [
            {
                "memory_id": item.get("memory_id", ""),
                "display_text": item.get("display_text", ""),
                "event_summary": item.get("event_summary", ""),
                "structure_refs": list(item.get("structure_refs", [])),
                "structure_ref_items": self._resolve_structure_refs(
                    structure_store,
                    item.get("structure_refs", []),
                ),
                "group_refs": list(item.get("group_refs", [])),
                "group_ref_items": self._resolve_group_refs(
                    group_store,
                    structure_store,
                    item.get("group_refs", []),
                ),
                "backing_structure_ids": list(item.get("backing_structure_ids", [])),
                "source_structure_ids": list(item.get("source_structure_ids", [])),
                "er": round(float(item.get("er", 0.0)), 8),
                "ev": round(float(item.get("ev", 0.0)), 8),
                "total_energy": round(float(item.get("er", 0.0)) + float(item.get("ev", 0.0)), 8),
                "last_delta_er": round(float(item.get("last_delta_er", 0.0)), 8),
                "last_delta_ev": round(float(item.get("last_delta_ev", 0.0)), 8),
                "last_decay_delta_er": round(float(item.get("last_decay_delta_er", 0.0)), 8),
                "last_decay_delta_ev": round(float(item.get("last_decay_delta_ev", 0.0)), 8),
                "total_delta_er": round(float(item.get("total_delta_er", 0.0)), 8),
                "total_delta_ev": round(float(item.get("total_delta_ev", 0.0)), 8),
                "mode_totals": dict(item.get("mode_totals", {})),
                "mode_totals_er": dict(item.get("mode_totals_er", {})),
                "mode_totals_ev": dict(item.get("mode_totals_ev", {})),
                "hit_count": int(item.get("hit_count", 0)),
                "update_count": int(item.get("update_count", 0)),
                "recent_events": list(item.get("recent_events", [])),
                "feedback_count": int(item.get("feedback_count", 0)),
                "last_feedback_er": round(float(item.get("last_feedback_er", 0.0)), 8),
                "last_feedback_ev": round(float(item.get("last_feedback_ev", 0.0)), 8),
                "total_feedback_er": round(float(item.get("total_feedback_er", 0.0)), 8),
                "total_feedback_ev": round(float(item.get("total_feedback_ev", 0.0)), 8),
                "last_feedback_at": int(item.get("last_feedback_at", 0)),
                "recent_feedback_events": list(item.get("recent_feedback_events", [])),
                "created_at": item.get("created_at", 0),
                "last_updated_at": item.get("last_updated_at", 0),
                "last_trace_id": item.get("last_trace_id", ""),
                "last_tick_id": item.get("last_tick_id", ""),
            }
            for item in sorted(
                memory_activation_items,
                key=lambda item: (
                    -(float(item.get("er", 0.0)) + float(item.get("ev", 0.0))),
                    -float(item.get("last_updated_at", 0.0)),
                    str(item.get("memory_id", "")),
                ),
            )[:top_k]
        ]
        snapshot["repair_jobs"] = [
            {
                "repair_job_id": job.get("repair_job_id", ""),
                "status": job.get("status", ""),
                "scope": job.get("repair_scope", ""),
                "target_id": job.get("target_id", ""),
                "processed_count": job.get("processed_count", 0),
                "repaired_count": job.get("repaired_count", 0),
            }
            for job in sorted(active_jobs, key=lambda item: item.get("created_at", 0), reverse=True)[:top_k]
        ]
        snapshot["issues"] = list(issue_queue[-top_k:])
        return snapshot

    @staticmethod
    def _is_contextual_diff_entry(entry: dict, *, owner_structure_id: str) -> bool:
        if not isinstance(entry, dict):
            return False
        context = extract_context_metadata(entry)
        path_depth = context_path_depth(entry)
        ref_object_id = str(context.get("context_ref_object_id", "") or "").strip()
        context_owner_structure_id = str(context.get("context_owner_structure_id", "") or "").strip()
        if path_depth > 1:
            return True
        if ref_object_id and ref_object_id != owner_structure_id:
            return True
        if context_owner_structure_id and context_owner_structure_id != owner_structure_id:
            return True
        return False

    @staticmethod
    def _is_residual_local_diff_entry(entry: dict) -> bool:
        if not isinstance(entry, dict):
            return False
        relation_type = str(entry.get("ext", {}).get("relation_type", "") or "").strip()
        residual = extract_residual_metadata(entry)
        residual_kind = str(residual.get("residual_origin_kind", "") or "").strip()
        return bool(
            relation_type == "incoming_extension"
            or "residual" in relation_type
            or "residual" in residual_kind
            or relation_type == "structure_raw_residual"
            or relation_type == "stimulus_raw_residual"
            or relation_type == "residual_context_common"
        )

    def _summarize_issue_types(self, issue_queue: list[dict]) -> dict[str, int]:
        summary: dict[str, int] = {}
        for item in issue_queue[-200:]:
            issue_type = item.get("issue_type", "unknown")
            summary[issue_type] = summary.get(issue_type, 0) + 1
        return summary

    def _resolve_structure_refs(self, structure_store, structure_ids: list[str]) -> list[dict]:
        refs = []
        for structure_id in structure_ids or []:
            structure_obj = structure_store.get(structure_id)
            if not structure_obj:
                refs.append(
                    {
                        "structure_id": structure_id,
                        "display_text": structure_id,
                        "content_signature": "",
                        "exists": False,
                    }
                )
                continue
            refs.append(
                {
                    "structure_id": structure_id,
                    "display_text": structure_obj.get("structure", {}).get("display_text", structure_id),
                    "content_signature": structure_obj.get("structure", {}).get("content_signature", ""),
                    "exists": True,
                }
            )
        return refs

    def _resolve_group_refs(self, group_store, structure_store, group_ids: list[str]) -> list[dict]:
        refs = []
        for group_id in group_ids or []:
            group_obj = group_store.get(group_id)
            if not group_obj:
                refs.append(
                    {
                        "group_id": group_id,
                        "required_structures": [],
                        "bias_structures": [],
                        "exists": False,
                    }
                )
                continue
            refs.append(
                {
                    "group_id": group_id,
                    "required_structures": self._resolve_structure_refs(
                        structure_store,
                        group_obj.get("required_structure_ids", []),
                    ),
                    "bias_structures": self._resolve_structure_refs(
                        structure_store,
                        group_obj.get("bias_structure_ids", []),
                    ),
                    "exists": True,
                }
            )
        return refs
