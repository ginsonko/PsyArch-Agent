# -*- coding: utf-8 -*-
"""
Self-check engine for HDB.
"""

from __future__ import annotations


class SelfCheckEngine:
    def __init__(self, config: dict):
        self._config = config

    def update_config(self, config: dict) -> None:
        self._config = config

    def run(
        self,
        *,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        pointer_index,
        trace_id: str,
        target_id: str | None = None,
        check_scope: str = "quick",
        max_items: int | None = None,
        include_orphans: bool = True,
    ) -> dict:
        max_items = max_items or int(self._config.get("fallback_scan_hard_limit", 200))
        issues: list[dict] = []
        checked_structure_count = 0
        checked_group_count = 0
        checked_episodic_count = 0
        checked_memory_activation_count = 0

        structure_items, group_items, episodic_items, memory_items = self._pick_targets(
            structure_store=structure_store,
            group_store=group_store,
            episodic_store=episodic_store,
            memory_activation_store=memory_activation_store,
            target_id=target_id,
            check_scope=check_scope,
            max_items=max_items,
        )

        for structure_obj in structure_items:
            if not structure_obj:
                continue
            checked_structure_count += 1
            issues.extend(self._check_structure(structure_obj, structure_store, group_store, pointer_index))
            if len(issues) >= max_items:
                break

        if len(issues) < max_items:
            for group_obj in group_items:
                if not group_obj:
                    continue
                checked_group_count += 1
                issues.extend(self._check_group(group_obj, structure_store))
                if len(issues) >= max_items:
                    break

        if len(issues) < max_items:
            for episodic_obj in episodic_items:
                if not episodic_obj:
                    continue
                checked_episodic_count += 1
                issues.extend(self._check_episodic(episodic_obj, structure_store, group_store))
                if len(issues) >= max_items:
                    break

        if len(issues) < max_items:
            for memory_item in memory_items:
                if not memory_item:
                    continue
                checked_memory_activation_count += 1
                issues.extend(self._check_memory_activation(memory_item, episodic_store, structure_store, group_store))
                if len(issues) >= max_items:
                    break

        if include_orphans and len(issues) < max_items and check_scope != "quick":
            owner_ids = {item.get("id", "") for item in structure_store.iter_structures()}
            for structure_db in structure_store.iter_structure_dbs()[:max_items]:
                owner_id = structure_db.get("owner_structure_id", "")
                if owner_id and owner_id not in owner_ids:
                    issues.append(
                        {
                            "type": "orphan_structure_db",
                            "target_id": structure_db.get("structure_db_id", ""),
                            "owner_structure_id": owner_id,
                            "repair_suggestion": ["remove_orphan"],
                        }
                    )
                    if len(issues) >= max_items:
                        break

        return {
            "checked_structure_count": checked_structure_count,
            "checked_group_count": checked_group_count,
            "checked_episodic_count": checked_episodic_count,
            "checked_memory_activation_count": checked_memory_activation_count,
            "issue_count": len(issues),
            "issues": issues[:max_items],
            "trace_id": trace_id,
        }

    def _pick_targets(
        self,
        *,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        target_id: str | None,
        check_scope: str,
        max_items: int,
    ) -> tuple[list[dict], list[dict], list[dict], list[dict]]:
        if target_id:
            if target_id.startswith("st_"):
                return ([structure_store.get(target_id)] if structure_store.get(target_id) else [], [], [], [])
            if target_id.startswith("sg_"):
                return ([], [group_store.get(target_id)] if group_store.get(target_id) else [], [], [])
            if target_id.startswith("em_"):
                episodic_items = [episodic_store.get(target_id)] if episodic_store.get(target_id) else []
                memory_items = [memory_activation_store.get(target_id)] if memory_activation_store.get(target_id) else []
                return ([], [], episodic_items, memory_items)
            if target_id.startswith("sdb_"):
                structure_db = structure_store.get_db(target_id)
                owner_id = structure_db.get("owner_structure_id", "") if structure_db else ""
                return ([structure_store.get(owner_id)] if owner_id and structure_store.get(owner_id) else [], [], [], [])
            return ([], [], [], [])

        return (
            self._pick_structures(structure_store, check_scope, max_items),
            self._pick_groups(group_store, check_scope, max_items),
            self._pick_episodic(episodic_store, check_scope, max_items),
            self._pick_memory_activations(memory_activation_store, check_scope, max_items),
        )

    def _pick_structures(self, structure_store, check_scope: str, max_items: int) -> list[dict]:
        if check_scope in {"quick", "structure_only"}:
            if hasattr(structure_store, "get_recent_structures"):
                return structure_store.get_recent_structures(max_items)
            items = structure_store.iter_structures()
            return sorted(items, key=lambda item: item.get("updated_at", 0), reverse=True)[:max_items]
        items = structure_store.iter_structures()
        return items[:max_items]

    def _pick_groups(self, group_store, check_scope: str, max_items: int) -> list[dict]:
        if check_scope in {"episodic_only", "memory_activation_only"}:
            return []
        if check_scope in {"quick", "group_only"}:
            if hasattr(group_store, "get_recent"):
                return group_store.get_recent(max_items)
            items = group_store.iter_items()
            return sorted(items, key=lambda item: item.get("updated_at", 0), reverse=True)[:max_items]
        items = group_store.iter_items()
        return items[:max_items]

    def _pick_episodic(self, episodic_store, check_scope: str, max_items: int) -> list[dict]:
        if check_scope in {"structure_only", "group_only", "memory_activation_only"}:
            return []
        if check_scope in {"quick", "episodic_only"}:
            if hasattr(episodic_store, "get_recent"):
                return episodic_store.get_recent(max_items)
            items = episodic_store.iter_items()
            return sorted(items, key=lambda item: item.get("updated_at", 0), reverse=True)[:max_items]
        items = episodic_store.iter_items()
        return items[:max_items]

    def _pick_memory_activations(self, memory_activation_store, check_scope: str, max_items: int) -> list[dict]:
        if check_scope in {"structure_only", "group_only"}:
            return []
        if check_scope in {"quick", "memory_activation_only"}:
            if hasattr(memory_activation_store, "get_recent"):
                return memory_activation_store.get_recent(max_items)
            items = memory_activation_store.iter_items()
            return sorted(items, key=lambda item: item.get("last_updated_at", 0), reverse=True)[:max_items]
        items = memory_activation_store.iter_items()
        return items[:max_items]

    def _check_structure(self, structure_obj: dict, structure_store, group_store, pointer_index) -> list[dict]:
        issues = []
        structure_id = structure_obj.get("id", "")
        structure_block = structure_obj.get("structure", {})
        db_pointer = structure_obj.get("db_pointer", {})
        structure_db_id = db_pointer.get("structure_db_id", "")
        structure_db = structure_store.get_db(structure_db_id) if structure_db_id else None

        if not structure_block.get("display_text", ""):
            issues.append(
                {
                    "type": "invalid_structure_display",
                    "target_id": structure_id,
                    "repair_suggestion": ["refresh_structure_metadata"],
                }
            )
        if not structure_block.get("content_signature", ""):
            issues.append(
                {
                    "type": "missing_content_signature",
                    "target_id": structure_id,
                    "repair_suggestion": ["refresh_structure_metadata"],
                }
            )

        if structure_db is None:
            issues.append(
                {
                    "type": "missing_pointer",
                    "target_id": structure_id,
                    "missing_structure_db_id": structure_db_id,
                    "repair_suggestion": ["rebuild_pointer"],
                }
            )
            return issues

        if structure_db.get("owner_structure_id") != structure_id:
            issues.append(
                {
                    "type": "pointer_owner_mismatch",
                    "target_id": structure_id,
                    "structure_db_id": structure_db_id,
                    "actual_owner_structure_id": structure_db.get("owner_structure_id", ""),
                    "repair_suggestion": ["rebuild_pointer"],
                }
            )

        expected_pointer_status = "ok"
        if db_pointer.get("pointer_status", expected_pointer_status) not in {"ok", "repaired"}:
            issues.append(
                {
                    "type": "pointer_status_invalid",
                    "target_id": structure_id,
                    "pointer_status": db_pointer.get("pointer_status", ""),
                    "repair_suggestion": ["rebuild_pointer"],
                }
            )

        structure_signature = structure_block.get("content_signature", "")
        if pointer_index is not None and structure_signature:
            pointer_hits = pointer_index.query_candidates_by_signature(structure_signature)
            if structure_id not in pointer_hits:
                issues.append(
                    {
                        "type": "pointer_index_missing",
                        "target_id": structure_id,
                        "content_signature": structure_signature,
                        "repair_suggestion": ["rebuild_pointer"],
                    }
                )

        for entry in structure_db.get("diff_table", []):
            target_id = str(entry.get("target_id", ""))
            target_db_id = str(entry.get("target_db_id", ""))
            if target_id and not structure_store.get(target_id):
                issues.append(
                    {
                        "type": "dangling_diff_ref",
                        "target_id": structure_id,
                        "entry_id": entry.get("entry_id", ""),
                        "missing_ref": target_id,
                        "repair_suggestion": ["drop_invalid_entry"],
                    }
                )
            elif target_db_id:
                target_obj = structure_store.get(target_id) if target_id else None
                actual_target_db_id = str(target_obj.get("db_pointer", {}).get("structure_db_id", "")) if target_obj else ""
                if actual_target_db_id and actual_target_db_id != target_db_id:
                    issues.append(
                        {
                            "type": "stale_diff_target_db_pointer",
                            "target_id": structure_id,
                            "entry_id": entry.get("entry_id", ""),
                            "target_structure_id": target_id,
                            "stored_target_db_id": target_db_id,
                            "actual_target_db_id": actual_target_db_id,
                            "repair_suggestion": ["refresh_structure_db_links"],
                        }
                    )

        for entry in structure_db.get("group_table", []):
            group_id = str(entry.get("group_id", ""))
            required_ids = [str(ref_id) for ref_id in entry.get("required_structure_ids", []) if str(ref_id)]
            if group_id and not group_store.get(group_id):
                issues.append(
                    {
                        "type": "dangling_group_table_group_ref",
                        "target_id": structure_id,
                        "group_id": group_id,
                        "repair_suggestion": ["drop_invalid_entry"],
                    }
                )
            for ref_id in required_ids:
                if not structure_store.get(ref_id):
                    issues.append(
                        {
                            "type": "dangling_local_group_ref",
                            "target_id": structure_id,
                            "group_id": group_id,
                            "missing_ref": ref_id,
                            "repair_suggestion": ["drop_invalid_entry"],
                        }
                    )
            if group_id:
                group_obj = group_store.get(group_id)
                if group_obj:
                    group_required_ids = [str(ref_id) for ref_id in group_obj.get("required_structure_ids", []) if str(ref_id)]
                    if required_ids and group_required_ids and set(required_ids) != set(group_required_ids):
                        issues.append(
                            {
                                "type": "group_table_profile_mismatch",
                                "target_id": structure_id,
                                "group_id": group_id,
                                "repair_suggestion": ["refresh_structure_db_links"],
                            }
                        )
        return issues

    def _check_group(self, group_obj: dict, structure_store) -> list[dict]:
        issues = []
        group_id = group_obj.get("id", "")
        required_ids = [str(structure_id) for structure_id in group_obj.get("required_structure_ids", []) if str(structure_id)]
        bias_ids = [str(structure_id) for structure_id in group_obj.get("bias_structure_ids", []) if str(structure_id)]
        if not required_ids:
            issues.append(
                {
                    "type": "empty_group_required_refs",
                    "target_id": group_id,
                    "repair_suggestion": ["delete_empty_group"],
                }
            )
        for structure_id in required_ids:
            if not structure_store.get(structure_id):
                issues.append(
                    {
                        "type": "dangling_group_ref",
                        "target_id": group_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["drop_invalid_entry"],
                    }
                )
        for structure_id in bias_ids:
            if not structure_store.get(structure_id):
                issues.append(
                    {
                        "type": "dangling_bias_ref",
                        "target_id": group_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["drop_invalid_entry"],
                    }
                )
        avg_energy_profile = group_obj.get("avg_energy_profile", {}) or {}
        profile_keys = {str(key) for key in avg_energy_profile.keys() if str(key)}
        required_key_set = set(required_ids)
        if profile_keys and required_key_set and not required_key_set.issubset(profile_keys):
            issues.append(
                {
                    "type": "group_energy_profile_incomplete",
                    "target_id": group_id,
                    "repair_suggestion": ["refresh_group_profile"],
                }
            )
        return issues

    def _check_episodic(self, episodic_obj: dict, structure_store, group_store) -> list[dict]:
        issues = []
        episodic_id = episodic_obj.get("id", "")
        for structure_id in episodic_obj.get("structure_refs", []):
            if structure_id and not structure_store.get(structure_id):
                issues.append(
                    {
                        "type": "dangling_episodic_structure_ref",
                        "target_id": episodic_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["reindex_episodic_ref"],
                    }
                )
        for group_id in episodic_obj.get("group_refs", []):
            if group_id and not group_store.get(group_id):
                issues.append(
                    {
                        "type": "dangling_episodic_group_ref",
                        "target_id": episodic_id,
                        "missing_ref": group_id,
                        "repair_suggestion": ["reindex_episodic_ref"],
                    }
                )
        memory_material = dict(episodic_obj.get("meta", {}).get("ext", {}).get("memory_material", {}) or {})
        structure_energy_profile = dict(memory_material.get("structure_energy_profile", {}) or {})
        if structure_energy_profile:
            missing_profile_refs = [key for key in structure_energy_profile.keys() if key and not structure_store.get(str(key))]
            if missing_profile_refs:
                issues.append(
                    {
                        "type": "dangling_memory_material_structure_profile_ref",
                        "target_id": episodic_id,
                        "missing_refs": missing_profile_refs,
                        "repair_suggestion": ["refresh_memory_material"],
                    }
                )
        for structure_item in memory_material.get("structure_items", []) or []:
            structure_id = str(structure_item.get("structure_id", ""))
            if structure_id and not structure_store.get(structure_id):
                issues.append(
                    {
                        "type": "dangling_memory_material_structure_item_ref",
                        "target_id": episodic_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["refresh_memory_material"],
                    }
                )
        return issues

    def _check_memory_activation(self, item: dict, episodic_store, structure_store, group_store) -> list[dict]:
        issues = []
        memory_id = str(item.get("memory_id", item.get("id", "")))
        episodic_obj = episodic_store.get(memory_id)
        if episodic_obj is None:
            issues.append(
                {
                    "type": "orphan_memory_activation",
                    "target_id": memory_id,
                    "repair_suggestion": ["drop_orphan_memory_activation"],
                }
            )
            return issues

        live_structure_refs = {str(ref_id) for ref_id in episodic_obj.get("structure_refs", []) if str(ref_id)}
        live_group_refs = {str(ref_id) for ref_id in episodic_obj.get("group_refs", []) if str(ref_id)}

        for structure_id in item.get("structure_refs", []) or []:
            structure_id = str(structure_id)
            if structure_id and not structure_store.get(structure_id):
                issues.append(
                    {
                        "type": "dangling_memory_activation_structure_ref",
                        "target_id": memory_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["refresh_memory_activation_refs"],
                    }
                )

        for group_id in item.get("group_refs", []) or []:
            group_id = str(group_id)
            if group_id and not group_store.get(group_id):
                issues.append(
                    {
                        "type": "dangling_memory_activation_group_ref",
                        "target_id": memory_id,
                        "missing_ref": group_id,
                        "repair_suggestion": ["refresh_memory_activation_refs"],
                    }
                )

        item_structure_refs = {str(ref_id) for ref_id in item.get("structure_refs", []) if str(ref_id)}
        item_group_refs = {str(ref_id) for ref_id in item.get("group_refs", []) if str(ref_id)}
        if item_structure_refs != live_structure_refs or item_group_refs != live_group_refs:
            issues.append(
                {
                    "type": "memory_activation_ref_mismatch",
                    "target_id": memory_id,
                    "repair_suggestion": ["refresh_memory_activation_refs"],
                }
            )

        for structure_id in item.get("backing_structure_ids", []) or []:
            if structure_id and not structure_store.get(str(structure_id)):
                issues.append(
                    {
                        "type": "dangling_memory_activation_backing_ref",
                        "target_id": memory_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["refresh_memory_activation_refs"],
                    }
                )
        for structure_id in item.get("source_structure_ids", []) or []:
            if structure_id and not structure_store.get(str(structure_id)):
                issues.append(
                    {
                        "type": "dangling_memory_activation_source_ref",
                        "target_id": memory_id,
                        "missing_ref": structure_id,
                        "repair_suggestion": ["refresh_memory_activation_refs"],
                    }
                )
        return issues
