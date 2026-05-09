# -*- coding: utf-8 -*-
"""
Delete and clear engine for HDB.
"""

from __future__ import annotations

from pathlib import Path

from ._storage_utils import list_json_files, remove_file


class DeleteEngine:
    def __init__(self, config: dict):
        self._config = config

    def update_config(self, config: dict) -> None:
        self._config = config

    def delete_structure(
        self,
        *,
        structure_id: str,
        delete_mode: str,
        structure_store,
        group_store,
        pointer_index,
        issue_callback,
    ) -> dict:
        structure_obj = structure_store.get(structure_id)
        if structure_obj is None:
            return {"deleted": False, "reason": "not_found", "detached_ref_count": 0, "deleted_group_count": 0}

        detached_ref_count = 0
        deleted_group_count = 0

        if delete_mode == "safe_detach":
            for candidate in structure_store.iter_structures():
                structure_db = structure_store.get_db_by_owner(candidate.get("id", ""))
                if not structure_db:
                    continue
                original_len = len(structure_db.get("diff_table", []))
                structure_db["diff_table"] = [entry for entry in structure_db.get("diff_table", []) if entry.get("target_id", "") != structure_id]
                detached_ref_count += max(0, original_len - len(structure_db["diff_table"]))
                group_table = []
                for entry in structure_db.get("group_table", []):
                    required_ids = [sid for sid in entry.get("required_structure_ids", []) if sid != structure_id]
                    if required_ids:
                        entry["required_structure_ids"] = required_ids
                        group_table.append(entry)
                    else:
                        detached_ref_count += 1
                structure_db["group_table"] = group_table
                structure_store.update_db(structure_db)

            for group_obj in list(group_store.iter_items()):
                required_ids = [sid for sid in group_obj.get("required_structure_ids", []) if sid != structure_id]
                bias_ids = [sid for sid in group_obj.get("bias_structure_ids", []) if sid != structure_id]
                if not required_ids:
                    group_store.delete(group_obj.get("id", ""))
                    deleted_group_count += 1
                    continue
                if len(required_ids) != len(group_obj.get("required_structure_ids", [])) or len(bias_ids) != len(group_obj.get("bias_structure_ids", [])):
                    detached_ref_count += 1
                    group_obj["required_structure_ids"] = required_ids
                    group_obj["bias_structure_ids"] = bias_ids
                    group_store.update(group_obj)

        if delete_mode == "force_delete":
            issue_callback({
                "issue_type": "force_deleted_structure",
                "target_id": structure_id,
                "repair_suggestion": ["self_check_hdb"],
            })

        structure_signature = structure_obj.get("structure", {}).get("content_signature", "")
        deleted = structure_store.delete_structure(structure_id)
        pointer_index.unregister_structure(structure_id, structure_signature)
        return {
            "deleted": bool(deleted.get("deleted") or deleted.get("db_deleted")),
            "reason": delete_mode,
            "structure_db_id": deleted.get("structure_db_id", ""),
            "detached_ref_count": detached_ref_count,
            "deleted_group_count": deleted_group_count,
        }

    def clear_hdb(
        self,
        *,
        clear_mode: str,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        pointer_index,
        issue_queue: list[dict],
        repair_jobs: dict[str, dict],
        repair_dir: str | Path | None = None,
    ) -> dict:
        summary = {
            "cleared_structure_count": 0,
            "cleared_group_count": 0,
            "cleared_episodic_count": 0,
            "cleared_memory_activation_count": 0,
            "cleared_issue_count": 0,
            "cleared_repair_job_count": 0,
            "cleared_repair_file_count": 0,
        }

        if clear_mode in {"full", "structures_only"}:
            cleared = structure_store.clear_structures()
            summary["cleared_structure_count"] = cleared.get("structure_count", 0)
            pointer_index.rebuild_from_store(structure_store)

        if clear_mode in {"full", "groups_only", "structures_only"}:
            summary["cleared_group_count"] = group_store.clear()

        if clear_mode in {"full", "episodic_only"}:
            summary["cleared_episodic_count"] = episodic_store.clear()

        if clear_mode in {"full", "episodic_only", "structures_only"}:
            summary["cleared_memory_activation_count"] = memory_activation_store.clear()

        if clear_mode == "full":
            summary["cleared_issue_count"] = len(issue_queue)
            summary["cleared_repair_job_count"] = len(repair_jobs)
            issue_queue.clear()
            repair_jobs.clear()
            if repair_dir:
                repair_path = Path(repair_dir)
                for path in list_json_files(repair_path):
                    if remove_file(path):
                        summary["cleared_repair_file_count"] += 1

        return summary
