# -*- coding: utf-8 -*-
"""
Maintenance helpers for HDB soft limits and index refresh.
"""

from __future__ import annotations

from ._owner_runtime_budget import owner_persistence_trim_enabled


class MaintenanceEngine:
    def __init__(self, config: dict):
        self._config = config

    def update_config(self, config: dict) -> None:
        self._config = config

    def apply_structure_db_soft_limits(self, structure_db: dict) -> dict:
        structure_db["diff_table"] = self._merge_duplicate_diff_entries(structure_db.get("diff_table", []))
        if owner_persistence_trim_enabled(self._config):
            diff_limit = int(self._config.get("diff_table_soft_limit", 128))
            group_limit = int(self._config.get("group_table_soft_limit", 128))
            structure_db["diff_table"] = self._trim_table(
                structure_db.get("diff_table", []),
                diff_limit,
            )
            structure_db["group_table"] = self._trim_table(structure_db.get("group_table", []), group_limit)
        else:
            structure_db["group_table"] = list(structure_db.get("group_table", []))
        return structure_db

    def _merge_duplicate_diff_entries(self, entries: list[dict]) -> list[dict]:
        merged: list[dict] = []
        by_key: dict[tuple, dict] = {}
        for raw in list(entries or []):
            entry = dict(raw or {})
            key = self._diff_merge_key(entry)
            if key is None:
                merged.append(entry)
                continue
            existing = by_key.get(key)
            if existing is None:
                by_key[key] = entry
                merged.append(entry)
                continue
            self._merge_diff_entry_into(existing, entry)
        return merged

    @staticmethod
    def _diff_merge_key(entry: dict) -> tuple | None:
        entry_type = str(entry.get("entry_type", "structure_ref") or "structure_ref")
        ext = entry.get("ext", {}) if isinstance(entry.get("ext", {}), dict) else {}
        relation_type = str(ext.get("relation_type", "") or "")
        if entry_type == "raw_residual":
            signature = str(entry.get("canonical_content_signature", "") or entry.get("content_signature", "") or "")
        else:
            signature = str(entry.get("content_signature", "") or "")
        if not signature:
            return None
        if entry_type == "structure_ref" and relation_type not in {
            "residual_context_common",
            "incoming_extension",
            "structure_raw_residual",
        }:
            return None
        return (
            entry_type,
            relation_type,
            signature,
            str(entry.get("residual_existing_signature", "") or ""),
            str(entry.get("residual_incoming_signature", "") or ""),
            str(ext.get("context_owner_structure_id", "") or ext.get("owner_structure_id", "") or ""),
            str(ext.get("context_ref_object_id", "") or ""),
            str(ext.get("context_ref_object_type", "") or ""),
        )

    @staticmethod
    def _merge_unique_list(left: list, right: list, limit: int = 32) -> list:
        out = []
        for value in list(left or []) + list(right or []):
            text = str(value or "")
            if text and text not in out:
                out.append(text)
            if len(out) >= limit:
                break
        return out

    def _merge_diff_entry_into(self, target: dict, source: dict) -> None:
        target["base_weight"] = round(
            float(target.get("base_weight", 0.0) or 0.0) + max(0.0, float(source.get("base_weight", 0.0) or 0.0)),
            6,
        )
        target["recent_gain"] = max(float(target.get("recent_gain", 1.0) or 1.0), float(source.get("recent_gain", 1.0) or 1.0))
        target["fatigue"] = min(float(target.get("fatigue", 0.0) or 0.0), float(source.get("fatigue", 0.0) or 0.0))
        target["runtime_er"] = round(float(target.get("runtime_er", 0.0) or 0.0) + float(source.get("runtime_er", 0.0) or 0.0), 8)
        target["runtime_ev"] = round(float(target.get("runtime_ev", 0.0) or 0.0) + float(source.get("runtime_ev", 0.0) or 0.0), 8)
        target["match_count_total"] = int(target.get("match_count_total", 0) or 0) + int(source.get("match_count_total", 0) or 0)
        target["last_updated_at"] = max(int(target.get("last_updated_at", 0) or 0), int(source.get("last_updated_at", 0) or 0))
        target["last_matched_at"] = max(int(target.get("last_matched_at", 0) or 0), int(source.get("last_matched_at", 0) or 0))
        target["memory_refs"] = self._merge_unique_list(target.get("memory_refs", []), source.get("memory_refs", []), limit=64)
        target_ids = self._merge_unique_list(
            [target.get("target_id", "")] + list(target.get("target_alias_ids", []) or []),
            [source.get("target_id", "")] + list(source.get("target_alias_ids", []) or []),
            limit=32,
        )
        if target_ids:
            target["target_id"] = target_ids[0]
            target["target_alias_ids"] = target_ids
        ext = dict(target.get("ext", {}) if isinstance(target.get("ext", {}), dict) else {})
        source_ext = source.get("ext", {}) if isinstance(source.get("ext", {}), dict) else {}
        ext.update(source_ext)
        ext["merged_duplicate_diff_entry_count"] = int(ext.get("merged_duplicate_diff_entry_count", 0) or 0) + 1
        target["ext"] = ext

    def _trim_table(self, entries: list[dict], limit: int) -> list[dict]:
        if limit <= 0 or len(entries) <= limit:
            return list(entries)
        scored = sorted(
            entries,
            key=lambda item: (
                float(item.get("base_weight", 0.0)) * float(item.get("recent_gain", 1.0)) / (1.0 + float(item.get("fatigue", 0.0))),
                int(item.get("last_updated_at", item.get("last_matched_at", 0))),
            ),
            reverse=True,
        )
        return scored[:limit]
