# -*- coding: utf-8 -*-
"""
Repair engine for HDB.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path

from ._id_generator import next_id
from ._storage_utils import remove_file, write_json_file


class RepairEngine:
    def __init__(self, config: dict, repair_dir: str | Path, self_check_engine):
        self._config = config
        self._repair_dir = Path(repair_dir)
        self._self_check = self_check_engine
        self._jobs: dict[str, dict] = {}
        self._threads: dict[str, threading.Thread] = {}
        self._issue_callback = None
        self._lock = threading.Lock()

    @property
    def jobs(self) -> dict[str, dict]:
        return self._jobs

    def update_config(self, config: dict) -> None:
        self._config = config

    def set_issue_callback(self, issue_callback) -> None:
        self._issue_callback = issue_callback

    def stop_job(self, repair_job_id: str) -> dict:
        job = self._jobs.get(repair_job_id)
        if not job:
            return {"success": False, "code": "STATE_ERROR", "already_finished": False}
        if job.get("status") in {"completed", "stopped", "timeout", "failed"}:
            return {"success": True, "code": "OK", "already_finished": True}
        job["stop_requested"] = True
        job["status"] = "stopping"
        self._persist_job(job)
        return {"success": True, "code": "OK", "already_finished": False}

    def start_or_run(
        self,
        *,
        trace_id: str,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        pointer_index,
        delete_engine,
        target_id: str | None,
        repair_scope: str,
        repair_actions: list[str] | None,
        batch_limit: int,
        allow_delete_unrecoverable: bool,
        background: bool,
    ) -> dict:
        job = {
            "repair_job_id": next_id("repair_job"),
            "trace_id": trace_id,
            "target_id": target_id or "",
            "repair_scope": repair_scope,
            "repair_actions": list(repair_actions or []),
            "batch_limit": batch_limit,
            "allow_delete_unrecoverable": allow_delete_unrecoverable,
            "background": background,
            "status": "pending",
            "stop_requested": False,
            "created_at": int(time.time() * 1000),
            "started_at": 0,
            "updated_at": 0,
            "finished_at": 0,
            "processed_count": 0,
            "repaired_count": 0,
            "deleted_count": 0,
            "issue_count": 0,
            "actions_applied": [],
            "errors": [],
        }
        self._jobs[job["repair_job_id"]] = job
        self._persist_job(job)

        kwargs = {
            "job": job,
            "structure_store": structure_store,
            "group_store": group_store,
            "episodic_store": episodic_store,
            "memory_activation_store": memory_activation_store,
            "pointer_index": pointer_index,
            "delete_engine": delete_engine,
            "target_id": target_id,
            "repair_scope": repair_scope,
            "repair_actions": repair_actions or [],
            "batch_limit": batch_limit,
            "allow_delete_unrecoverable": allow_delete_unrecoverable,
        }

        if background and self._config.get("enable_background_repair", True):
            thread = threading.Thread(target=self._execute_job, kwargs=kwargs, daemon=True)
            self._threads[job["repair_job_id"]] = thread
            thread.start()
            return {"repair_job_id": job["repair_job_id"], "background": True, "status": job["status"]}

        self._execute_job(**kwargs)
        return dict(self._jobs.get(job["repair_job_id"], job))

    def _execute_job(
        self,
        *,
        job: dict,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        pointer_index,
        delete_engine,
        target_id: str | None,
        repair_scope: str,
        repair_actions: list[str],
        batch_limit: int,
        allow_delete_unrecoverable: bool,
    ) -> None:
        start_ms = int(time.time() * 1000)
        max_runtime_ms = int(self._config.get("max_repair_runtime_ms", 30000))
        repair_actions = repair_actions or [
            "rebuild_pointer",
            "drop_invalid_entry",
            "reindex_episodic_ref",
            "recompute_counts",
            "refresh_structure_db_links",
            "refresh_group_profile",
            "refresh_memory_material",
            "refresh_memory_activation_refs",
            "refresh_structure_metadata",
            "drop_orphan_memory_activation",
        ]

        job["status"] = "running"
        job["started_at"] = start_ms
        job["updated_at"] = start_ms
        self._persist_job(job)

        targets = self._select_targets(
            structure_store=structure_store,
            group_store=group_store,
            episodic_store=episodic_store,
            memory_activation_store=memory_activation_store,
            target_id=target_id,
            repair_scope=repair_scope,
            batch_limit=batch_limit,
        )
        job["issue_count"] = len(targets)
        self._persist_job(job)

        for index, item in enumerate(targets, start=1):
            if job.get("stop_requested"):
                job["status"] = "stopped"
                break
            if int(time.time() * 1000) - start_ms > max_runtime_ms:
                job["status"] = "timeout"
                break

            try:
                result = self._repair_target(
                    target=item,
                    repair_actions=repair_actions,
                    structure_store=structure_store,
                    group_store=group_store,
                    episodic_store=episodic_store,
                    memory_activation_store=memory_activation_store,
                    pointer_index=pointer_index,
                    delete_engine=delete_engine,
                    allow_delete_unrecoverable=allow_delete_unrecoverable,
                )
                job["processed_count"] += 1
                job["repaired_count"] += int(result.get("repaired", False))
                job["deleted_count"] += int(result.get("deleted", False))
                if result.get("actions_applied"):
                    job["actions_applied"].append(
                        {
                            "target_id": item.get("target_id", ""),
                            "actions": result.get("actions_applied", []),
                        }
                    )
            except Exception as exc:  # pragma: no cover
                job["errors"].append({"target_id": item.get("target_id", ""), "error": str(exc)})

            job["updated_at"] = int(time.time() * 1000)
            self._persist_job(job)
            if index % max(1, batch_limit) == 0:
                time.sleep(float(self._config.get("repair_sleep_ms_between_batches", 10)) / 1000.0)

        if job.get("status") == "running":
            job["status"] = "completed"
        job["finished_at"] = int(time.time() * 1000)
        job["updated_at"] = job["finished_at"]
        self._persist_job(job)

    def _select_targets(
        self,
        *,
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        target_id: str | None,
        repair_scope: str,
        batch_limit: int,
    ) -> list[dict]:
        if target_id:
            return [{"target_id": target_id, "issue_type": "targeted"}]

        check_scope = "full" if repair_scope == "global_full" else "quick"
        check_result = self._self_check.run(
            structure_store=structure_store,
            group_store=group_store,
            episodic_store=episodic_store,
            memory_activation_store=memory_activation_store,
            pointer_index=None,
            trace_id="repair_precheck",
            target_id=None,
            check_scope=check_scope,
            max_items=batch_limit,
            include_orphans=True,
        )
        issues = list(check_result.get("issues", []))
        if issues:
            return [
                {"target_id": item.get("target_id", ""), "issue_type": item.get("type", "unknown")}
                for item in issues
                if item.get("target_id")
            ][:batch_limit]

        fallback_targets = [
            {"target_id": item.get("id", ""), "issue_type": "recompute_counts"}
            for item in structure_store.get_recent_structures(limit=batch_limit)
        ]
        return fallback_targets[:batch_limit]

    def _repair_target(
        self,
        *,
        target: dict,
        repair_actions: list[str],
        structure_store,
        group_store,
        episodic_store,
        memory_activation_store,
        pointer_index,
        delete_engine,
        allow_delete_unrecoverable: bool,
    ) -> dict:
        target_id = str(target.get("target_id", ""))
        actions_applied = []
        deleted = False
        repaired = False

        if target_id.startswith("st_"):
            structure_obj = structure_store.get(target_id)
            if structure_obj is None:
                return {"repaired": False, "deleted": False, "actions_applied": []}

            structure_db_id = str(structure_obj.get("db_pointer", {}).get("structure_db_id", ""))
            structure_db = structure_store.get_db(structure_db_id) if structure_db_id else None

            if "rebuild_pointer" in repair_actions and (not structure_db or structure_db.get("owner_structure_id") != target_id):
                owner_db = structure_store.get_db_by_owner(target_id)
                if owner_db:
                    structure_obj.setdefault("db_pointer", {})["structure_db_id"] = owner_db.get("structure_db_id", "")
                    structure_obj["db_pointer"]["pointer_status"] = "repaired"
                    structure_store.update_structure(structure_obj)
                    if pointer_index is not None:
                        pointer_index.register_structure(structure_obj)
                    actions_applied.append("rebuild_pointer")
                    repaired = True
                    structure_db = owner_db

            if structure_db and "drop_invalid_entry" in repair_actions:
                before_diff = len(structure_db.get("diff_table", []))
                refreshed_diff = []
                for entry in structure_db.get("diff_table", []):
                    target_structure_id = str(entry.get("target_id", ""))
                    if target_structure_id and not structure_store.get(target_structure_id):
                        continue
                    refreshed_diff.append(entry)
                before_group = len(structure_db.get("group_table", []))
                refreshed_group = []
                for entry in structure_db.get("group_table", []):
                    group_id = str(entry.get("group_id", ""))
                    if group_id and not group_store.get(group_id):
                        continue
                    required_ids = [sid for sid in entry.get("required_structure_ids", []) if structure_store.get(str(sid))]
                    if len(required_ids) != len(entry.get("required_structure_ids", [])):
                        entry = dict(entry)
                        entry["required_structure_ids"] = required_ids
                    refreshed_group.append(entry)
                if before_diff != len(refreshed_diff) or before_group != len(refreshed_group):
                    structure_db["diff_table"] = refreshed_diff
                    structure_db["group_table"] = refreshed_group
                    structure_store.update_db(structure_db)
                    actions_applied.append("drop_invalid_entry")
                    repaired = True

            if structure_db and "refresh_structure_db_links" in repair_actions:
                changed = False
                refreshed_diff = []
                for entry in structure_db.get("diff_table", []):
                    target_structure_id = str(entry.get("target_id", ""))
                    if target_structure_id:
                        target_obj = structure_store.get(target_structure_id)
                        if target_obj is None:
                            continue
                        actual_target_db_id = str(target_obj.get("db_pointer", {}).get("structure_db_id", ""))
                        if actual_target_db_id and actual_target_db_id != str(entry.get("target_db_id", "")):
                            entry = dict(entry)
                            entry["target_db_id"] = actual_target_db_id
                            changed = True
                    refreshed_diff.append(entry)
                refreshed_group = []
                for entry in structure_db.get("group_table", []):
                    group_id = str(entry.get("group_id", ""))
                    if group_id:
                        group_obj = group_store.get(group_id)
                        if group_obj is None:
                            continue
                        group_required_ids = [sid for sid in group_obj.get("required_structure_ids", []) if structure_store.get(str(sid))]
                        if group_required_ids and group_required_ids != list(entry.get("required_structure_ids", [])):
                            entry = dict(entry)
                            entry["required_structure_ids"] = group_required_ids
                            changed = True
                    refreshed_group.append(entry)
                if changed:
                    structure_db["diff_table"] = refreshed_diff
                    structure_db["group_table"] = refreshed_group
                    structure_store.update_db(structure_db)
                    actions_applied.append("refresh_structure_db_links")
                    repaired = True

            if "refresh_structure_metadata" in repair_actions:
                structure_block = structure_obj.setdefault("structure", {})
                changed = False
                if not str(structure_block.get("display_text", "")):
                    structure_block["display_text"] = target_id
                    changed = True
                if not str(structure_block.get("content_signature", "")):
                    semantic_signature = str(structure_block.get("semantic_signature", ""))
                    token_fallback = "|".join(str(token) for token in structure_block.get("flat_tokens", []) if str(token))
                    structure_block["content_signature"] = semantic_signature or token_fallback or target_id
                    changed = True
                if changed:
                    structure_store.update_structure(structure_obj)
                    actions_applied.append("refresh_structure_metadata")
                    repaired = True

            if structure_db and "recompute_counts" in repair_actions:
                structure_db.setdefault("integrity", {})["issue_count"] = 0
                structure_db["integrity"]["last_check_at"] = int(time.time() * 1000)
                structure_store.update_db(structure_db)
                actions_applied.append("recompute_counts")
                repaired = True

            unresolved_db_id = str(structure_obj.get("db_pointer", {}).get("structure_db_id", ""))
            if allow_delete_unrecoverable and "rebuild_pointer" in repair_actions and structure_store.get_db(unresolved_db_id) is None:
                delete_engine.delete_structure(
                    structure_id=target_id,
                    delete_mode="force_delete",
                    structure_store=structure_store,
                    group_store=group_store,
                    pointer_index=pointer_index,
                    issue_callback=self._issue_callback or (lambda issue: None),
                )
                actions_applied.append("force_delete_unrecoverable")
                deleted = True

        elif target_id.startswith("sg_"):
            group_obj = group_store.get(target_id)
            if group_obj is None:
                return {"repaired": False, "deleted": False, "actions_applied": []}

            if "drop_invalid_entry" in repair_actions:
                required_ids = [sid for sid in group_obj.get("required_structure_ids", []) if structure_store.get(str(sid))]
                bias_ids = [sid for sid in group_obj.get("bias_structure_ids", []) if structure_store.get(str(sid))]
                if required_ids != group_obj.get("required_structure_ids", []) or bias_ids != group_obj.get("bias_structure_ids", []):
                    if required_ids:
                        group_obj["required_structure_ids"] = required_ids
                        group_obj["bias_structure_ids"] = bias_ids
                        group_store.update(group_obj)
                        repaired = True
                        actions_applied.append("drop_invalid_entry")
                    elif allow_delete_unrecoverable:
                        group_store.delete(target_id)
                        deleted = True
                        actions_applied.append("delete_empty_group")

            if not deleted and "refresh_group_profile" in repair_actions:
                required_ids = [sid for sid in group_obj.get("required_structure_ids", []) if structure_store.get(str(sid))]
                new_profile = {
                    str(structure_id): float(group_obj.get("avg_energy_profile", {}).get(str(structure_id), 1.0))
                    for structure_id in required_ids
                }
                if required_ids and (
                    required_ids != list(group_obj.get("required_structure_ids", []))
                    or set(new_profile.keys()) != set((group_obj.get("avg_energy_profile", {}) or {}).keys())
                ):
                    group_obj["required_structure_ids"] = required_ids
                    group_obj["avg_energy_profile"] = new_profile
                    group_store.update(group_obj)
                    repaired = True
                    actions_applied.append("refresh_group_profile")

        elif target_id.startswith("em_"):
            episodic_obj = episodic_store.get(target_id)
            memory_item = memory_activation_store.get(target_id)

            if episodic_obj is None:
                if memory_item is not None and "drop_orphan_memory_activation" in repair_actions:
                    memory_activation_store.delete(target_id)
                    return {"repaired": False, "deleted": True, "actions_applied": ["drop_orphan_memory_activation"]}
                return {"repaired": False, "deleted": False, "actions_applied": []}

            if "reindex_episodic_ref" in repair_actions:
                new_structure_refs = [sid for sid in episodic_obj.get("structure_refs", []) if structure_store.get(str(sid))]
                new_group_refs = [gid for gid in episodic_obj.get("group_refs", []) if group_store.get(str(gid))]
                if new_structure_refs != episodic_obj.get("structure_refs", []) or new_group_refs != episodic_obj.get("group_refs", []):
                    episodic_obj["structure_refs"] = new_structure_refs
                    episodic_obj["group_refs"] = new_group_refs
                    episodic_store.update(episodic_obj)
                    repaired = True
                    actions_applied.append("reindex_episodic_ref")

            if "refresh_memory_material" in repair_actions:
                memory_material = dict(episodic_obj.get("meta", {}).get("ext", {}).get("memory_material", {}) or {})
                changed = False
                structure_items = []
                for structure_item in memory_material.get("structure_items", []) or []:
                    structure_id = str(structure_item.get("structure_id", ""))
                    if structure_id and structure_store.get(structure_id):
                        structure_items.append(structure_item)
                    else:
                        changed = True
                structure_energy_profile = {
                    str(key): value
                    for key, value in dict(memory_material.get("structure_energy_profile", {}) or {}).items()
                    if str(key) and structure_store.get(str(key))
                }
                if changed or structure_energy_profile != dict(memory_material.get("structure_energy_profile", {}) or {}):
                    memory_material["structure_items"] = structure_items
                    memory_material["structure_energy_profile"] = structure_energy_profile
                    episodic_obj.setdefault("meta", {}).setdefault("ext", {})["memory_material"] = memory_material
                    episodic_store.update(episodic_obj)
                    repaired = True
                    actions_applied.append("refresh_memory_material")

            if memory_item is not None and "refresh_memory_activation_refs" in repair_actions:
                changed = False
                expected_structure_refs = list(episodic_obj.get("structure_refs", []))
                expected_group_refs = list(episodic_obj.get("group_refs", []))
                expected_backing_ids = [sid for sid in memory_item.get("backing_structure_ids", []) if structure_store.get(str(sid))]
                expected_source_ids = [sid for sid in memory_item.get("source_structure_ids", []) if structure_store.get(str(sid))]
                if list(memory_item.get("structure_refs", [])) != expected_structure_refs:
                    memory_item["structure_refs"] = expected_structure_refs
                    changed = True
                if list(memory_item.get("group_refs", [])) != expected_group_refs:
                    memory_item["group_refs"] = expected_group_refs
                    changed = True
                if list(memory_item.get("backing_structure_ids", [])) != expected_backing_ids:
                    memory_item["backing_structure_ids"] = expected_backing_ids
                    changed = True
                if list(memory_item.get("source_structure_ids", [])) != expected_source_ids:
                    memory_item["source_structure_ids"] = expected_source_ids
                    changed = True
                if changed:
                    memory_activation_store._persist_item(memory_item)
                    repaired = True
                    actions_applied.append("refresh_memory_activation_refs")

        elif target_id.startswith("sdb_") and allow_delete_unrecoverable:
            structure_db = structure_store.get_db(target_id)
            if structure_db and not structure_store.get(structure_db.get("owner_structure_id", "")):
                structure_store._structure_dbs.pop(target_id, None)
                remove_file(structure_store._db_file_path(target_id))
                deleted = True
                actions_applied.append("remove_orphan")

        return {"repaired": repaired, "deleted": deleted, "actions_applied": actions_applied}

    def _persist_job(self, job: dict) -> None:
        with self._lock:
            write_json_file(self._repair_dir / f"{job['repair_job_id']}.json", job)
