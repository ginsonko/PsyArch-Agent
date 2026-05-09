# -*- coding: utf-8 -*-
"""
Structure object and structure database storage for HDB.
"""

from __future__ import annotations

import time
import sqlite3
import threading
import zlib
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from itertools import islice
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from . import __module_name__, __schema_version__
from ._context_metadata import (
    build_context_metadata,
    context_path_depth,
    extract_context_metadata,
    extract_residual_metadata,
    has_context_metadata,
    merge_context_metadata,
    merge_residual_metadata,
)
from ._id_generator import ensure_counter, next_id
from ._storage_utils import dumps_json_bytes, list_json_files, load_json_file, loads_json_bytes, remove_file, write_json_file


class StructureStore:
    def __init__(self, structures_dir: str | Path, indexes_dir: str | Path, config: dict | None = None):
        self._structures_dir = Path(structures_dir)
        self._indexes_dir = Path(indexes_dir)
        self._config = config or {}
        self._storage_backend = self._normalize_storage_backend(self._config.get("structure_store_backend", "filesystem"))
        self._sqlite_conn: sqlite3.Connection | None = None
        self._sqlite_lock = threading.RLock()
        self._sqlite_path = self._resolve_sqlite_path()
        self._structures: dict[str, dict] = {}
        self._structure_dbs: dict[str, dict] = {}
        self._owner_to_db: dict[str, str] = {}
        self._persistence_batch_depth = 0
        self._dirty_structure_ids: set[str] = set()
        self._dirty_db_ids: set[str] = set()
        self._shared_runtime_cache: dict[str, OrderedDict] = {}
        self._runtime_revision = 0
        self._structure_lookup_revision = 0
        self._runtime_context_summary_core: dict[str, float | int] = self._empty_runtime_context_summary_core()
        self._structure_context_entries: dict[str, dict] = {}
        self._db_context_entries: dict[str, dict] = {}
        self._signature_context_counts: dict[str, dict[str, int]] = {}
        self._recent_structure_ids: list[str] = []
        self._init_storage_backend()
        self._load()
        self._rebuild_runtime_context_summary()

    @property
    def structure_count(self) -> int:
        return len(self._structures)

    @property
    def structure_db_count(self) -> int:
        return len(self._structure_dbs)

    @property
    def storage_backend(self) -> str:
        return self._storage_backend

    @staticmethod
    def _normalize_storage_backend(value: Any) -> str:
        backend = str(value or "filesystem").strip().lower()
        if backend in {"sqlite", "sqlite_wal", "wal"}:
            return "sqlite"
        return "filesystem"

    def _resolve_sqlite_path(self) -> Path:
        configured = str(self._config.get("structure_store_sqlite_path", "") or "").strip()
        if configured:
            return Path(configured)
        return self._indexes_dir.parent / "hdb_structure_store.sqlite3"

    def _init_storage_backend(self) -> None:
        if self._storage_backend != "sqlite":
            return
        with self._sqlite_lock:
            if self._sqlite_conn is not None:
                return
            self._sqlite_path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._sqlite_path), timeout=30.0, check_same_thread=False)
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=NORMAL")
            conn.execute("PRAGMA temp_store=MEMORY")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS structures (
                    id TEXT PRIMARY KEY,
                    payload BLOB NOT NULL,
                    codec TEXT NOT NULL DEFAULT 'json',
                    updated_at INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS structure_dbs (
                    structure_db_id TEXT PRIMARY KEY,
                    owner_structure_id TEXT UNIQUE,
                    payload BLOB NOT NULL,
                    codec TEXT NOT NULL DEFAULT 'json',
                    updated_at INTEGER NOT NULL DEFAULT 0
                )
                """
            )
            self._sqlite_ensure_column(conn, "structures", "codec", "TEXT NOT NULL DEFAULT 'json'")
            self._sqlite_ensure_column(conn, "structure_dbs", "codec", "TEXT NOT NULL DEFAULT 'json'")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_structure_dbs_owner ON structure_dbs(owner_structure_id)"
            )
            conn.commit()
            self._sqlite_conn = conn

    @staticmethod
    def _sqlite_ensure_column(conn: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
        existing = {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table})")}
        if column not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")

    @property
    def is_persistence_batching(self) -> bool:
        return self._persistence_batch_depth > 0

    @property
    def runtime_revision(self) -> int:
        return int(self._runtime_revision)

    @property
    def structure_lookup_revision(self) -> int:
        return int(self._structure_lookup_revision)

    @staticmethod
    def _empty_runtime_context_summary_core() -> dict[str, float | int]:
        return {
            "contextual_structure_count": 0,
            "multi_context_structure_count": 0,
            "structure_context_path_depth_total": 0.0,
            "same_content_multi_context_count": 0,
            "diff_entry_count": 0,
            "contextual_diff_entry_count": 0,
            "residual_diff_entry_count": 0,
            "diff_entry_with_memory_ref_count": 0,
        }

    def get_runtime_context_summary(self) -> dict[str, Any]:
        core = dict(self._runtime_context_summary_core or {})
        contextual_count = int(core.get("contextual_structure_count", 0) or 0)
        depth_total = float(core.get("structure_context_path_depth_total", 0.0) or 0.0)
        return {
            "contextual_structure_count": contextual_count,
            "multi_context_structure_count": int(core.get("multi_context_structure_count", 0) or 0),
            "structure_context_path_depth_mean": round(depth_total / float(contextual_count), 8) if contextual_count else 0.0,
            "same_content_multi_context_count": int(core.get("same_content_multi_context_count", 0) or 0),
            "diff_entry_count": int(core.get("diff_entry_count", 0) or 0),
            "contextual_diff_entry_count": int(core.get("contextual_diff_entry_count", 0) or 0),
            "residual_diff_entry_count": int(core.get("residual_diff_entry_count", 0) or 0),
            "diff_entry_with_memory_ref_count": int(core.get("diff_entry_with_memory_ref_count", 0) or 0),
        }

    @staticmethod
    def _structure_context_summary_entry(structure_obj: dict) -> dict[str, Any]:
        if not isinstance(structure_obj, dict):
            return {
                "contextual": 0,
                "multi_context": 0,
                "depth": 0.0,
                "signature": "",
                "context_key": "",
            }
        contextual = 1 if has_context_metadata(structure_obj) else 0
        depth = float(context_path_depth(structure_obj) if contextual else 0)
        context_meta = extract_context_metadata(structure_obj)
        signature = str(structure_obj.get("structure", {}).get("content_signature", "") or "").strip()
        context_key = str(
            context_meta.get("context_owner_structure_id")
            or context_meta.get("context_ref_object_id")
            or ""
        ).strip()
        return {
            "contextual": contextual,
            "multi_context": 1 if depth > 1 else 0,
            "depth": depth,
            "signature": signature,
            "context_key": context_key,
        }

    @staticmethod
    def _is_contextual_diff_entry_summary(entry: dict, *, owner_structure_id: str) -> bool:
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
    def _is_residual_local_diff_entry_summary(entry: dict) -> bool:
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

    def _db_context_summary_entry(self, structure_db: dict) -> dict[str, int]:
        if not isinstance(structure_db, dict):
            return {
                "diff_entry_count": 0,
                "contextual_diff_entry_count": 0,
                "residual_diff_entry_count": 0,
                "diff_entry_with_memory_ref_count": 0,
            }
        owner_structure_id = str(structure_db.get("owner_structure_id", "") or "")
        diff_entry_count = 0
        contextual_diff_entry_count = 0
        residual_diff_entry_count = 0
        diff_entry_with_memory_ref_count = 0
        for entry in list(structure_db.get("diff_table", []) or []):
            if not isinstance(entry, dict):
                continue
            diff_entry_count += 1
            if entry.get("memory_refs"):
                diff_entry_with_memory_ref_count += 1
            if self._is_contextual_diff_entry_summary(entry, owner_structure_id=owner_structure_id):
                contextual_diff_entry_count += 1
            if self._is_residual_local_diff_entry_summary(entry):
                residual_diff_entry_count += 1
        return {
            "diff_entry_count": int(diff_entry_count),
            "contextual_diff_entry_count": int(contextual_diff_entry_count),
            "residual_diff_entry_count": int(residual_diff_entry_count),
            "diff_entry_with_memory_ref_count": int(diff_entry_with_memory_ref_count),
        }

    def _add_structure_context_entry(self, structure_id: str, entry: dict[str, Any]) -> None:
        self._structure_context_entries[structure_id] = dict(entry)
        self._runtime_context_summary_core["contextual_structure_count"] = int(
            self._runtime_context_summary_core.get("contextual_structure_count", 0) or 0
        ) + int(entry.get("contextual", 0) or 0)
        self._runtime_context_summary_core["multi_context_structure_count"] = int(
            self._runtime_context_summary_core.get("multi_context_structure_count", 0) or 0
        ) + int(entry.get("multi_context", 0) or 0)
        self._runtime_context_summary_core["structure_context_path_depth_total"] = float(
            self._runtime_context_summary_core.get("structure_context_path_depth_total", 0.0) or 0.0
        ) + float(entry.get("depth", 0.0) or 0.0)
        signature = str(entry.get("signature", "") or "")
        context_key = str(entry.get("context_key", "") or "")
        if signature and context_key:
            bucket = self._signature_context_counts.setdefault(signature, {})
            unique_before = len(bucket)
            bucket[context_key] = int(bucket.get(context_key, 0) or 0) + 1
            unique_after = len(bucket)
            if unique_before <= 1 and unique_after > 1:
                self._runtime_context_summary_core["same_content_multi_context_count"] = int(
                    self._runtime_context_summary_core.get("same_content_multi_context_count", 0) or 0
                ) + 1

    def _remove_structure_context_entry(self, structure_id: str) -> None:
        entry = self._structure_context_entries.pop(structure_id, None)
        if not isinstance(entry, dict):
            return
        self._runtime_context_summary_core["contextual_structure_count"] = max(
            0,
            int(self._runtime_context_summary_core.get("contextual_structure_count", 0) or 0)
            - int(entry.get("contextual", 0) or 0),
        )
        self._runtime_context_summary_core["multi_context_structure_count"] = max(
            0,
            int(self._runtime_context_summary_core.get("multi_context_structure_count", 0) or 0)
            - int(entry.get("multi_context", 0) or 0),
        )
        self._runtime_context_summary_core["structure_context_path_depth_total"] = max(
            0.0,
            float(self._runtime_context_summary_core.get("structure_context_path_depth_total", 0.0) or 0.0)
            - float(entry.get("depth", 0.0) or 0.0),
        )
        signature = str(entry.get("signature", "") or "")
        context_key = str(entry.get("context_key", "") or "")
        if signature and context_key:
            bucket = self._signature_context_counts.get(signature, {})
            if isinstance(bucket, dict) and context_key in bucket:
                unique_before = len(bucket)
                bucket[context_key] = int(bucket.get(context_key, 0) or 0) - 1
                if bucket[context_key] <= 0:
                    bucket.pop(context_key, None)
                unique_after = len(bucket)
                if unique_before > 1 and unique_after <= 1:
                    self._runtime_context_summary_core["same_content_multi_context_count"] = max(
                        0,
                        int(self._runtime_context_summary_core.get("same_content_multi_context_count", 0) or 0) - 1,
                    )
                if not bucket:
                    self._signature_context_counts.pop(signature, None)

    def _add_db_context_entry(self, structure_db_id: str, entry: dict[str, int]) -> None:
        self._db_context_entries[structure_db_id] = dict(entry)
        for key in (
            "diff_entry_count",
            "contextual_diff_entry_count",
            "residual_diff_entry_count",
            "diff_entry_with_memory_ref_count",
        ):
            self._runtime_context_summary_core[key] = int(
                self._runtime_context_summary_core.get(key, 0) or 0
            ) + int(entry.get(key, 0) or 0)

    def _remove_db_context_entry(self, structure_db_id: str) -> None:
        entry = self._db_context_entries.pop(structure_db_id, None)
        if not isinstance(entry, dict):
            return
        for key in (
            "diff_entry_count",
            "contextual_diff_entry_count",
            "residual_diff_entry_count",
            "diff_entry_with_memory_ref_count",
        ):
            self._runtime_context_summary_core[key] = max(
                0,
                int(self._runtime_context_summary_core.get(key, 0) or 0) - int(entry.get(key, 0) or 0),
            )

    def _rebuild_runtime_context_summary(self) -> None:
        self._runtime_context_summary_core = self._empty_runtime_context_summary_core()
        self._structure_context_entries.clear()
        self._db_context_entries.clear()
        self._signature_context_counts.clear()
        for structure_id, structure_obj in self._structures.items():
            self._add_structure_context_entry(
                str(structure_id),
                self._structure_context_summary_entry(structure_obj),
            )
        for structure_db_id, structure_db in self._structure_dbs.items():
            self._add_db_context_entry(
                str(structure_db_id),
                self._db_context_summary_entry(structure_db),
            )

    def _recency_peak(self) -> float:
        return max(1.0, float(self._config.get("recency_gain_peak", 10.0)))

    def _recency_hold_rounds(self) -> int:
        return max(0, int(self._config.get("recency_gain_hold_rounds", 2)))

    def _recency_refresh_floor(self) -> float:
        return max(0.0, min(1.0, float(self._config.get("recency_gain_refresh_floor", 0.45))))

    def _new_recent_gain(self) -> float:
        return round(self._recency_peak(), 8)

    def _refresh_recent_gain(self, current: float, *, strength: float = 1.0) -> float:
        bounded_strength = max(self._recency_refresh_floor(), min(1.0, float(strength)))
        peak = self._recency_peak()
        return round(min(peak, max(float(current), 1.0 + (peak - 1.0) * bounded_strength)), 8)

    def create_structure(
        self,
        *,
        structure_payload: dict,
        trace_id: str,
        tick_id: str = "",
        source_interface: str = "run_stimulus_level_retrieval_storage",
        origin: str = "direct_store",
        origin_id: str = "",
        parent_ids: list[str] | None = None,
    ) -> tuple[dict, dict]:
        now_ms = int(time.time() * 1000)
        structure_id = next_id("st")
        structure_db_id = next_id("sdb")
        parent_ids = list(parent_ids or [])
        payload_ext = dict(structure_payload.get("ext", {})) if isinstance(structure_payload.get("ext", {}), dict) else {}
        payload_meta = dict(structure_payload.get("meta", {})) if isinstance(structure_payload.get("meta", {}), dict) else {}
        payload_meta_ext = dict(payload_meta.get("ext", {})) if isinstance(payload_meta.get("ext", {}), dict) else {}
        context_owner_structure_id = str(
            payload_ext.get("context_owner_structure_id")
            or payload_ext.get("owner_structure_id")
            or payload_meta_ext.get("context_owner_structure_id")
            or ""
        )
        context_ref_object_type = str(
            payload_ext.get("context_ref_object_type")
            or payload_meta_ext.get("context_ref_object_type")
            or ""
        )
        payload_ext = merge_context_metadata(
            payload_ext,
            context_owner_structure_id=context_owner_structure_id,
            context_ref_object_type=context_ref_object_type,
            parent_ids=parent_ids,
        )
        payload_ext = merge_residual_metadata(payload_ext)
        payload_meta_ext = merge_context_metadata(
            payload_meta_ext,
            context_owner_structure_id=context_owner_structure_id,
            context_ref_object_type=context_ref_object_type,
            parent_ids=parent_ids,
        )
        payload_meta_ext = merge_residual_metadata(payload_meta_ext)
        payload_context = build_context_metadata(
            context_ref_object_id=payload_ext.get("context_ref_object_id", ""),
            context_ref_object_type=payload_ext.get("context_ref_object_type", ""),
            context_owner_structure_id=payload_ext.get("context_owner_structure_id", ""),
            context_path_ids=payload_ext.get("context_path_ids", []),
            parent_ids=parent_ids,
        )

        structure_obj = {
            "id": structure_id,
            "object_type": "st",
            "sub_type": structure_payload.get("sub_type", "stimulus_sequence_structure"),
            "schema_version": __schema_version__,
            "structure": {
                "unit_type": structure_payload.get("unit_type", "sa_csa_sequence"),
                "display_text": structure_payload.get("display_text", structure_id),
                "member_refs": list(structure_payload.get("member_refs", [])),
                "sequence_groups": list(structure_payload.get("sequence_groups", [])),
                "flat_tokens": list(structure_payload.get("flat_tokens", [])),
                "content_signature": structure_payload.get("content_signature", structure_id),
                "semantic_signature": structure_payload.get(
                    "semantic_signature",
                    structure_payload.get("content_signature", structure_id),
                ),
                "token_count": len(structure_payload.get("flat_tokens", [])),
                "ext": payload_ext,
            },
            "db_pointer": {
                "structure_db_id": structure_db_id,
                "pointer_status": "ok",
                "fallback_index_key": structure_id,
                "last_known_parent_db": structure_payload.get("last_known_parent_db", ""),
            },
            "stats": {
                "base_weight": structure_payload.get("base_weight", 0.0),
                "recent_gain": structure_payload.get("recent_gain", self._new_recent_gain()),
                "fatigue": structure_payload.get("fatigue", 0.0),
                "runtime_er": structure_payload.get("runtime_er", 0.0),
                "runtime_ev": structure_payload.get("runtime_ev", 0.0),
                "last_runtime_energy_at": now_ms,
                "last_matched_at": structure_payload.get("last_matched_at", 0),
                "last_recency_refresh_at": structure_payload.get("last_recency_refresh_at", now_ms),
                "recency_hold_rounds_remaining": structure_payload.get("recency_hold_rounds_remaining", self._recency_hold_rounds()),
                "last_verified_by_er_at": structure_payload.get("last_verified_by_er_at", 0),
                "last_worn_by_ev_at": structure_payload.get("last_worn_by_ev_at", 0),
                "match_count_total": structure_payload.get("match_count_total", 0),
                "verified_count_er": structure_payload.get("verified_count_er", 0),
                "worn_count_ev": structure_payload.get("worn_count_ev", 0),
            },
            "source": {
                "module": __module_name__,
                "interface": source_interface,
                "origin": origin,
                "origin_id": origin_id,
                "parent_ids": parent_ids,
                **payload_context,
            },
            "trace_id": trace_id,
            "tick_id": tick_id or trace_id,
            "created_at": now_ms,
            "updated_at": now_ms,
            "status": "active",
            "meta": structure_payload.get(
                "meta",
                {
                    "confidence": structure_payload.get("confidence", 0.8),
                    "field_registry_version": __schema_version__,
                    "debug": {},
                    "ext": payload_meta_ext or payload_ext,
                },
            ),
        }
        if payload_meta:
            payload_meta["ext"] = payload_meta_ext
            structure_obj["meta"] = payload_meta

        structure_db = {
            "structure_db_id": structure_db_id,
            "owner_structure_id": structure_id,
            "diff_table": list(structure_payload.get("diff_table", [])),
            "group_table": list(structure_payload.get("group_table", [])),
            "integrity": {
                "pointer_ok": True,
                "last_check_at": 0,
                "issue_count": 0,
            },
            "created_at": now_ms,
            "updated_at": now_ms,
        }

        self._structures[structure_id] = structure_obj
        self._structure_dbs[structure_db_id] = structure_db
        self._owner_to_db[structure_id] = structure_db_id
        self._recent_structure_ids.append(structure_id)
        self._add_structure_context_entry(structure_id, self._structure_context_summary_entry(structure_obj))
        self._add_db_context_entry(structure_db_id, self._db_context_summary_entry(structure_db))
        self._runtime_revision += 1
        self._structure_lookup_revision += 1
        self._schedule_structure_persist(structure_id)
        self._schedule_db_persist(structure_db_id)
        return structure_obj, structure_db

    def get(self, structure_id: str) -> dict | None:
        return self._structures.get(structure_id)

    def iter_structures(self) -> list[dict]:
        return list(self._structures.values())

    def iter_structure_dbs(self) -> list[dict]:
        return list(self._structure_dbs.values())

    def get_db(self, structure_db_id: str) -> dict | None:
        return self._structure_dbs.get(structure_db_id)

    def get_db_by_owner(self, structure_id: str) -> dict | None:
        structure_db_id = self._owner_to_db.get(structure_id)
        if not structure_db_id:
            return None
        return self._structure_dbs.get(structure_db_id)

    def update_structure(self, structure_obj: dict) -> None:
        if not structure_obj.get("id"):
            return
        structure_obj["updated_at"] = int(time.time() * 1000)
        structure_id = str(structure_obj["id"])
        self._remove_structure_context_entry(structure_id)
        self._structures[structure_id] = structure_obj
        self._add_structure_context_entry(structure_id, self._structure_context_summary_entry(structure_obj))
        self._runtime_revision += 1
        self._structure_lookup_revision += 1
        self._schedule_structure_persist(structure_id)

    def update_db(self, structure_db: dict) -> None:
        structure_db_id = structure_db.get("structure_db_id")
        if not structure_db_id:
            return
        structure_db["updated_at"] = int(time.time() * 1000)
        structure_db_id = str(structure_db_id)
        self._remove_db_context_entry(structure_db_id)
        self._structure_dbs[structure_db_id] = structure_db
        owner_id = structure_db.get("owner_structure_id", "")
        if owner_id:
            self._owner_to_db[owner_id] = structure_db_id
        self._add_db_context_entry(structure_db_id, self._db_context_summary_entry(structure_db))
        self._runtime_revision += 1
        self._schedule_db_persist(structure_db_id)

    def update_config(self, config: dict) -> None:
        self._config = config or {}
        backend = self._normalize_storage_backend(self._config.get("structure_store_backend", self._storage_backend))
        sqlite_path = self._resolve_sqlite_path()
        if backend == self._storage_backend and sqlite_path == self._sqlite_path:
            return
        # Backend switching is intentionally lifecycle-scoped. Hot reload may
        # update tuning knobs, but changing the storage container while the HDB
        # is live would require a migration step and can hide dirty writes.
        self._config["structure_store_backend"] = self._storage_backend
        self._config["structure_store_sqlite_path"] = str(self._sqlite_path)

    def close(self) -> None:
        try:
            self.flush_pending_persistence()
        except Exception:
            pass
        with self._sqlite_lock:
            if self._sqlite_conn is not None:
                try:
                    self._sqlite_conn.commit()
                except Exception:
                    pass
                try:
                    self._sqlite_conn.close()
                finally:
                    self._sqlite_conn = None

    def _shared_runtime_cache_limit(self) -> int:
        try:
            limit = int(self._config.get("shared_runtime_cache_max_entries", 16384) or 16384)
        except Exception:
            limit = 16384
        return max(64, limit)

    def get_shared_runtime_cache_entry(self, namespace: str, key):
        bucket = self._shared_runtime_cache.get(str(namespace or ""))
        if not isinstance(bucket, OrderedDict):
            return None
        if key not in bucket:
            return None
        value = bucket.pop(key)
        bucket[key] = value
        return value

    def set_shared_runtime_cache_entry(self, namespace: str, key, value):
        namespace = str(namespace or "")
        if not namespace:
            return value
        bucket = self._shared_runtime_cache.setdefault(namespace, OrderedDict())
        if key in bucket:
            bucket.pop(key)
        bucket[key] = value
        limit = self._shared_runtime_cache_limit()
        while len(bucket) > limit:
            bucket.popitem(last=False)
        return value

    def clear_shared_runtime_cache(self) -> dict:
        namespace_count = len(self._shared_runtime_cache)
        entry_count = 0
        for bucket in self._shared_runtime_cache.values():
            try:
                entry_count += len(bucket)
            except Exception:
                continue
        self._shared_runtime_cache.clear()
        return {
            "namespace_count": int(namespace_count),
            "entry_count": int(entry_count),
        }

    def begin_persistence_batch(self) -> None:
        self._persistence_batch_depth += 1

    def end_persistence_batch(self, *, flush: bool = True) -> dict:
        if self._persistence_batch_depth > 0:
            self._persistence_batch_depth -= 1
        if self._persistence_batch_depth > 0 or not flush:
            return {"structure_count": 0, "db_count": 0, "batched": self.is_persistence_batching}
        return self.flush_pending_persistence()

    @contextmanager
    def batch_persistence(self, *, flush: bool = True):
        self.begin_persistence_batch()
        try:
            yield self
        finally:
            self.end_persistence_batch(flush=flush)

    def flush_pending_persistence(self) -> dict:
        started = time.perf_counter()
        dirty_structure_ids = sorted(
            structure_id
            for structure_id in self._dirty_structure_ids
            if structure_id in self._structures
        )
        dirty_db_ids = sorted(
            structure_db_id
            for structure_db_id in self._dirty_db_ids
            if structure_db_id in self._structure_dbs
        )
        collect_elapsed_ms = int((time.perf_counter() - started) * 1000)
        pending_total = len(dirty_structure_ids) + len(dirty_db_ids)
        if self._storage_backend == "sqlite":
            return self._flush_pending_persistence_sqlite(
                started=started,
                collect_elapsed_ms=collect_elapsed_ms,
                dirty_structure_ids=dirty_structure_ids,
                dirty_db_ids=dirty_db_ids,
            )
        parallel_enabled = self._parallel_persistence_flush_enabled(pending_total)
        parallel_workers = self._parallel_persistence_flush_workers(pending_total) if parallel_enabled else 0
        structure_started = time.perf_counter()
        structure_bytes_total = 0
        db_bytes_total = 0
        if parallel_enabled and dirty_structure_ids:
            with ThreadPoolExecutor(max_workers=parallel_workers, thread_name_prefix="hdb-struct-flush") as executor:
                structure_bytes_total = sum(
                    int(value or 0)
                    for value in executor.map(lambda sid: self._persist_structure(self._structures[sid]), dirty_structure_ids)
                )
        else:
            for structure_id in dirty_structure_ids:
                structure_bytes_total += int(self._persist_structure(self._structures[structure_id]) or 0)
        structure_elapsed_ms = int((time.perf_counter() - structure_started) * 1000)
        db_started = time.perf_counter()
        if parallel_enabled and dirty_db_ids:
            with ThreadPoolExecutor(max_workers=parallel_workers, thread_name_prefix="hdb-db-flush") as executor:
                db_bytes_total = sum(
                    int(value or 0)
                    for value in executor.map(lambda dbid: self._persist_db(self._structure_dbs[dbid]), dirty_db_ids)
                )
        else:
            for structure_db_id in dirty_db_ids:
                db_bytes_total += int(self._persist_db(self._structure_dbs[structure_db_id]) or 0)
        db_elapsed_ms = int((time.perf_counter() - db_started) * 1000)
        self._dirty_structure_ids.difference_update(dirty_structure_ids)
        self._dirty_db_ids.difference_update(dirty_db_ids)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "structure_count": len(dirty_structure_ids),
            "db_count": len(dirty_db_ids),
            "batched": False,
            "elapsed_ms": elapsed_ms,
            "collect_elapsed_ms": collect_elapsed_ms,
            "structure_elapsed_ms": structure_elapsed_ms,
            "db_elapsed_ms": db_elapsed_ms,
            "structure_bytes_total": int(structure_bytes_total),
            "db_bytes_total": int(db_bytes_total),
            "bytes_total": int(structure_bytes_total + db_bytes_total),
            "structure_bytes_per_file_mean": round(float(structure_bytes_total) / max(1, len(dirty_structure_ids)), 3),
            "db_bytes_per_file_mean": round(float(db_bytes_total) / max(1, len(dirty_db_ids)), 3),
            "dirty_structure_pending_count_before": len(dirty_structure_ids),
            "dirty_db_pending_count_before": len(dirty_db_ids),
            "parallel_enabled": bool(parallel_enabled),
            "parallel_workers": int(parallel_workers),
            "backend": self._storage_backend,
        }

    def _flush_pending_persistence_sqlite(
        self,
        *,
        started: float,
        collect_elapsed_ms: int,
        dirty_structure_ids: list[str],
        dirty_db_ids: list[str],
    ) -> dict:
        pending_total = len(dirty_structure_ids) + len(dirty_db_ids)
        structure_started = time.perf_counter()
        structure_bytes_total = 0
        db_bytes_total = 0
        sqlite_commit_elapsed_ms = 0
        if pending_total > 0:
            with self._sqlite_lock:
                conn = self._require_sqlite_conn()
                try:
                    for structure_id in dirty_structure_ids:
                        structure_bytes_total += int(
                            self._sqlite_upsert_structure(self._structures[structure_id], commit=False) or 0
                        )
                    structure_elapsed_ms = int((time.perf_counter() - structure_started) * 1000)
                    db_started = time.perf_counter()
                    for structure_db_id in dirty_db_ids:
                        db_bytes_total += int(
                            self._sqlite_upsert_db(self._structure_dbs[structure_db_id], commit=False) or 0
                        )
                    db_elapsed_ms = int((time.perf_counter() - db_started) * 1000)
                    commit_started = time.perf_counter()
                    conn.commit()
                    sqlite_commit_elapsed_ms = int((time.perf_counter() - commit_started) * 1000)
                except Exception:
                    try:
                        conn.rollback()
                    except Exception:
                        pass
                    raise
        else:
            structure_elapsed_ms = int((time.perf_counter() - structure_started) * 1000)
            db_elapsed_ms = 0
        self._dirty_structure_ids.difference_update(dirty_structure_ids)
        self._dirty_db_ids.difference_update(dirty_db_ids)
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return {
            "structure_count": len(dirty_structure_ids),
            "db_count": len(dirty_db_ids),
            "batched": False,
            "elapsed_ms": elapsed_ms,
            "collect_elapsed_ms": collect_elapsed_ms,
            "structure_elapsed_ms": structure_elapsed_ms,
            "db_elapsed_ms": db_elapsed_ms,
            "structure_bytes_total": int(structure_bytes_total),
            "db_bytes_total": int(db_bytes_total),
            "bytes_total": int(structure_bytes_total + db_bytes_total),
            "structure_bytes_per_file_mean": round(float(structure_bytes_total) / max(1, len(dirty_structure_ids)), 3),
            "db_bytes_per_file_mean": round(float(db_bytes_total) / max(1, len(dirty_db_ids)), 3),
            "dirty_structure_pending_count_before": len(dirty_structure_ids),
            "dirty_db_pending_count_before": len(dirty_db_ids),
            "parallel_enabled": False,
            "parallel_workers": 0,
            "backend": "sqlite",
            "sqlite_path": str(self._sqlite_path),
            "sqlite_commit_elapsed_ms": int(sqlite_commit_elapsed_ms),
        }

    def _parallel_persistence_flush_enabled(self, pending_total: int) -> bool:
        if int(pending_total or 0) <= 1:
            return False
        if not bool(self._config.get("deferred_persistence_parallel_flush_enabled", True)):
            return False
        try:
            min_items = int(self._config.get("deferred_persistence_parallel_flush_min_items", 64) or 64)
        except Exception:
            min_items = 64
        return int(pending_total or 0) >= max(2, min_items)

    def _parallel_persistence_flush_workers(self, pending_total: int) -> int:
        try:
            configured = int(self._config.get("deferred_persistence_parallel_flush_workers", 8) or 8)
        except Exception:
            configured = 8
        configured = max(1, min(32, configured))
        return max(1, min(configured, int(pending_total or 1)))

    def add_diff_entry(
        self,
        owner_structure_id: str,
        *,
        target_id: str,
        content_signature: str,
        base_weight: float,
        entry_type: str = "structure_ref",
        residual_existing_signature: str = "",
        residual_incoming_signature: str = "",
        ext: dict | None = None,
    ) -> dict | None:
        structure_db = self.get_db_by_owner(owner_structure_id)
        if structure_db is None:
            return None
        now_ms = int(time.time() * 1000)
        target_db_id = ""
        target_structure = self.get(target_id)
        if target_structure:
            target_db_id = str(target_structure.get("db_pointer", {}).get("structure_db_id", ""))
        ext_payload = dict(ext or {})
        ext_payload = merge_context_metadata(
            ext_payload,
            context_ref_object_id=ext_payload.get("context_ref_object_id", "") or owner_structure_id,
            context_ref_object_type=ext_payload.get("context_ref_object_type", "") or "st",
            context_owner_structure_id=ext_payload.get("context_owner_structure_id", "") or ext_payload.get("owner_structure_id", "") or owner_structure_id,
            parent_ids=[owner_structure_id] if owner_structure_id else [],
        )
        ext_payload = merge_residual_metadata(ext_payload)
        relation_type = str(ext_payload.get("relation_type", ""))
        for existing in structure_db.setdefault("diff_table", []):
            if existing.get("entry_type", "structure_ref") != entry_type:
                continue
            if existing.get("content_signature", "") != content_signature:
                continue
            if existing.get("residual_existing_signature", "") != residual_existing_signature:
                continue
            if existing.get("residual_incoming_signature", "") != residual_incoming_signature:
                continue
            existing_relation_type = str(existing.get("ext", {}).get("relation_type", ""))
            if existing_relation_type != relation_type:
                continue
            if not self._diff_entries_share_residual_identity(
                existing,
                incoming_target_id=target_id,
                incoming_content_signature=content_signature,
                incoming_ext=ext_payload,
                relation_type=relation_type,
                entry_type=entry_type,
            ):
                continue
            incoming_base_weight = max(0.0, float(base_weight))
            reinforcement = max(0.01, incoming_base_weight * 0.2) if incoming_base_weight > 0.0 else 0.0
            existing["base_weight"] = round(float(existing.get("base_weight", 0.0)) + reinforcement, 6)
            existing["recent_gain"] = self._refresh_recent_gain(float(existing.get("recent_gain", 1.0)))
            existing["match_count_total"] = int(existing.get("match_count_total", 0)) + 1
            existing["last_updated_at"] = now_ms
            existing["last_recency_refresh_at"] = now_ms
            existing["recency_hold_rounds_remaining"] = self._recency_hold_rounds()
            existing_target_id = str(existing.get("target_id", "") or "")
            incoming_target_id = str(target_id or "")
            if (
                incoming_target_id
                and incoming_target_id != existing_target_id
                and self._diff_relation_allows_same_residual_merge(relation_type=relation_type, entry_type=entry_type)
            ):
                aliases = [
                    str(item)
                    for item in list(existing.get("target_alias_ids", []) or [])
                    if str(item)
                ]
                if existing_target_id and existing_target_id not in aliases:
                    aliases.append(existing_target_id)
                if incoming_target_id not in aliases:
                    aliases.append(incoming_target_id)
                existing["target_alias_ids"] = aliases[:16]
                existing.setdefault("ext", {})["merged_same_residual_target_count"] = len(aliases)
            elif target_db_id:
                existing["target_db_id"] = target_db_id
            merged_ext = dict(existing.get("ext", {}))
            merged_ext.update(ext_payload)
            merged_ext = merge_context_metadata(
                merged_ext,
                context_ref_object_id=merged_ext.get("context_ref_object_id", "") or owner_structure_id,
                context_ref_object_type=merged_ext.get("context_ref_object_type", "") or "st",
                context_owner_structure_id=merged_ext.get("context_owner_structure_id", "") or merged_ext.get("owner_structure_id", "") or owner_structure_id,
                parent_ids=[owner_structure_id] if owner_structure_id else [],
            )
            existing["ext"] = merge_residual_metadata(
                merged_ext,
                residual_origin_entry_id=existing.get("entry_id", ""),
            )
            self.update_db(structure_db)
            return existing
        entry_id = next_id("diff")
        entry_ext = merge_residual_metadata(ext_payload, residual_origin_entry_id=entry_id)
        entry = {
            "entry_id": entry_id,
            "entry_type": entry_type,
            "target_id": target_id,
            "target_db_id": target_db_id,
            "content_signature": content_signature,
            "base_weight": round(float(base_weight), 6),
            "runtime_er": 0.0,
            "runtime_ev": 0.0,
            "recent_gain": self._new_recent_gain(),
            "fatigue": 0.0,
            "match_count_total": 0,
            "last_updated_at": now_ms,
            "last_matched_at": 0,
            "last_recency_refresh_at": now_ms,
            "recency_hold_rounds_remaining": self._recency_hold_rounds(),
            "path_stats": {
                "verified_count_er": 0,
                "worn_count_ev": 0,
            },
            "residual_existing_signature": residual_existing_signature,
            "residual_incoming_signature": residual_incoming_signature,
            "ext": entry_ext,
        }
        structure_db.setdefault("diff_table", []).append(entry)
        self.update_db(structure_db)
        return entry

    @staticmethod
    def _diff_relation_allows_same_residual_merge(*, relation_type: str, entry_type: str) -> bool:
        if entry_type != "structure_ref":
            return False
        return str(relation_type or "") in {
            "residual_context_common",
            "incoming_extension",
            "structure_raw_residual",
        }

    def _diff_entries_share_residual_identity(
        self,
        existing: dict,
        *,
        incoming_target_id: str,
        incoming_content_signature: str,
        incoming_ext: dict,
        relation_type: str,
        entry_type: str,
    ) -> bool:
        existing_target_id = str(existing.get("target_id", "") or "")
        incoming_target_id = str(incoming_target_id or "")
        if existing_target_id == incoming_target_id:
            return True
        if not self._diff_relation_allows_same_residual_merge(relation_type=relation_type, entry_type=entry_type):
            return False

        # Within one owner DB, residual identity is the residual content plus the
        # local context. The concrete target structure id may differ after
        # materialization or repair; keeping both rows would make one residual
        # fragment compete with itself.
        existing_ext = existing.get("ext", {}) if isinstance(existing.get("ext", {}), dict) else {}
        context_keys = (
            "context_owner_structure_id",
            "context_ref_object_id",
            "context_ref_object_type",
            "owner_structure_id",
            "kind",
        )
        for key in context_keys:
            if str(existing_ext.get(key, "") or "") != str(incoming_ext.get(key, "") or ""):
                return False
        return bool(str(existing.get("content_signature", "") or "") == str(incoming_content_signature or ""))

    def add_group_table_entry(
        self,
        owner_structure_id: str,
        *,
        group_id: str,
        required_structure_ids: list[str],
        avg_energy_profile: dict[str, float],
        base_weight: float,
    ) -> dict | None:
        structure_db = self.get_db_by_owner(owner_structure_id)
        if structure_db is None:
            return None
        now_ms = int(time.time() * 1000)
        entry = {
            "group_id": group_id,
            "required_structure_ids": list(required_structure_ids),
            "avg_energy_profile": dict(avg_energy_profile),
            "base_weight": round(float(base_weight), 6),
            "recent_gain": self._new_recent_gain(),
            "fatigue": 0.0,
            "last_matched_at": 0,
            "last_recency_refresh_at": now_ms,
            "recency_hold_rounds_remaining": self._recency_hold_rounds(),
            "match_count_total": 0,
            "last_updated_at": now_ms,
        }
        group_table = structure_db.setdefault("group_table", [])
        if not any(existing.get("group_id") == group_id for existing in group_table):
            group_table.append(entry)
            self.update_db(structure_db)
        return entry

    def remove_diff_entries(
        self,
        owner_structure_id: str,
        *,
        predicate=None,
        entry_ids: list[str] | None = None,
    ) -> int:
        structure_db = self.get_db_by_owner(owner_structure_id)
        if structure_db is None:
            return 0
        entry_id_set = {str(entry_id) for entry_id in (entry_ids or []) if str(entry_id)}
        removed = 0
        retained = []
        for entry in structure_db.get("diff_table", []):
            should_remove = False
            if entry_id_set and str(entry.get("entry_id", "")) in entry_id_set:
                should_remove = True
            elif predicate is not None:
                try:
                    should_remove = bool(predicate(entry))
                except Exception:
                    should_remove = False
            if should_remove:
                removed += 1
                continue
            retained.append(entry)
        if removed:
            structure_db["diff_table"] = retained
            self.update_db(structure_db)
        return removed

    def delete_structure(self, structure_id: str) -> dict:
        structure_obj = self._structures.pop(structure_id, None)
        if structure_obj is None:
            return {"deleted": False, "db_deleted": False}
        try:
            self._recent_structure_ids.remove(structure_id)
        except ValueError:
            pass
        self._remove_structure_context_entry(structure_id)
        self._runtime_revision += 1
        self._structure_lookup_revision += 1
        structure_deleted = self._delete_persisted_structure(structure_id)
        db_deleted = False
        self._dirty_structure_ids.discard(structure_id)
        structure_db_id = structure_obj.get("db_pointer", {}).get("structure_db_id", "")
        if structure_db_id:
            self._remove_db_context_entry(str(structure_db_id))
            self._structure_dbs.pop(structure_db_id, None)
            self._owner_to_db.pop(structure_id, None)
            self._dirty_db_ids.discard(structure_db_id)
            db_deleted = self._delete_persisted_db(str(structure_db_id))
        return {"deleted": structure_deleted, "db_deleted": db_deleted, "structure_db_id": structure_db_id}

    def clear_structures(self) -> dict:
        structure_count = len(self._structures)
        db_count = len(self._structure_dbs)
        legacy_orphan_db_count = 0
        if self._storage_backend == "sqlite":
            self._clear_sqlite_rows()
            for path in list_json_files(self._indexes_dir):
                if remove_file(path):
                    legacy_orphan_db_count += 1
            for path in list_json_files(self._structures_dir):
                remove_file(path)
            orphan_db_count = legacy_orphan_db_count
        else:
            for structure_id in list(self._structures):
                self.delete_structure(structure_id)
            orphan_db_count = 0
            for path in list_json_files(self._indexes_dir):
                if remove_file(path):
                    orphan_db_count += 1
        self._structures.clear()
        self._structure_dbs.clear()
        self._owner_to_db.clear()
        self._recent_structure_ids.clear()
        self._dirty_structure_ids.clear()
        self._dirty_db_ids.clear()
        self._runtime_context_summary_core = self._empty_runtime_context_summary_core()
        self._structure_context_entries.clear()
        self._db_context_entries.clear()
        self._signature_context_counts.clear()
        self._runtime_revision += 1
        self._structure_lookup_revision += 1
        return {
            "structure_count": structure_count,
            "structure_db_count": db_count + orphan_db_count,
            "orphan_structure_db_count": orphan_db_count,
        }

    def get_recent_structures(self, limit: int = 10) -> list[dict]:
        if limit <= 0:
            return []
        recent = [
            self._structures[structure_id]
            for structure_id in islice(reversed(self._recent_structure_ids), limit)
            if structure_id in self._structures
        ]
        if len(recent) >= limit:
            return recent[:limit]
        seen = {str(item.get("id", "")) for item in recent}
        for structure_id in reversed(list(self._structures.keys())):
            if len(recent) >= limit:
                break
            if structure_id in seen:
                continue
            item = self._structures.get(structure_id)
            if item is not None:
                recent.append(item)
        return recent[:limit]

    def _structure_file_path(self, structure_id: str) -> Path:
        return self._structures_dir / f"{structure_id}.json"

    def _db_file_path(self, structure_db_id: str) -> Path:
        return self._indexes_dir / f"{structure_db_id}.json"

    def _delete_persisted_structure(self, structure_id: str) -> bool:
        if self._storage_backend == "sqlite":
            with self._sqlite_lock:
                conn = self._require_sqlite_conn()
                cursor = conn.execute("DELETE FROM structures WHERE id = ?", (str(structure_id),))
                conn.commit()
                return int(cursor.rowcount or 0) > 0
        return remove_file(self._structure_file_path(structure_id))

    def _delete_persisted_db(self, structure_db_id: str) -> bool:
        if self._storage_backend == "sqlite":
            with self._sqlite_lock:
                conn = self._require_sqlite_conn()
                cursor = conn.execute("DELETE FROM structure_dbs WHERE structure_db_id = ?", (str(structure_db_id),))
                conn.commit()
                return int(cursor.rowcount or 0) > 0
        return remove_file(self._db_file_path(structure_db_id))

    def _clear_sqlite_rows(self) -> None:
        with self._sqlite_lock:
            conn = self._require_sqlite_conn()
            with conn:
                conn.execute("DELETE FROM structures")
                conn.execute("DELETE FROM structure_dbs")

    def _persist_structure(self, structure_obj: dict) -> int:
        if self._storage_backend == "sqlite":
            return self._sqlite_upsert_structure(structure_obj)
        payload = self._compact_payload_for_persistence(structure_obj, payload_kind="structure")
        return write_json_file(self._structure_file_path(structure_obj["id"]), payload)

    def _persist_db(self, structure_db: dict) -> int:
        if self._storage_backend == "sqlite":
            return self._sqlite_upsert_db(structure_db)
        payload = self._compact_payload_for_persistence(structure_db, payload_kind="structure_db")
        return write_json_file(self._db_file_path(structure_db["structure_db_id"]), payload)

    def _require_sqlite_conn(self) -> sqlite3.Connection:
        if self._sqlite_conn is None:
            self._init_storage_backend()
        if self._sqlite_conn is None:
            raise RuntimeError("SQLite structure store backend is not initialized")
        return self._sqlite_conn

    def _sqlite_upsert_structure(self, structure_obj: dict, *, commit: bool = True) -> int:
        payload = self._compact_payload_for_persistence(structure_obj, payload_kind="structure")
        data, codec = self._encode_sqlite_payload(payload)
        updated_at = int(structure_obj.get("updated_at", 0) or 0)
        with self._sqlite_lock:
            conn = self._require_sqlite_conn()
            conn.execute(
                """
                INSERT INTO structures(id, payload, codec, updated_at)
                VALUES(?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    payload=excluded.payload,
                    codec=excluded.codec,
                    updated_at=excluded.updated_at
                """,
                (str(structure_obj["id"]), sqlite3.Binary(data), codec, updated_at),
            )
            if commit:
                conn.commit()
        return len(data)

    def _sqlite_upsert_db(self, structure_db: dict, *, commit: bool = True) -> int:
        payload = self._compact_payload_for_persistence(structure_db, payload_kind="structure_db")
        data, codec = self._encode_sqlite_payload(payload)
        updated_at = int(structure_db.get("updated_at", 0) or 0)
        with self._sqlite_lock:
            conn = self._require_sqlite_conn()
            conn.execute(
                """
                INSERT INTO structure_dbs(structure_db_id, owner_structure_id, payload, codec, updated_at)
                VALUES(?, ?, ?, ?, ?)
                ON CONFLICT(structure_db_id) DO UPDATE SET
                    owner_structure_id=excluded.owner_structure_id,
                    payload=excluded.payload,
                    codec=excluded.codec,
                    updated_at=excluded.updated_at
                """,
                (
                    str(structure_db["structure_db_id"]),
                    str(structure_db.get("owner_structure_id", "") or ""),
                    sqlite3.Binary(data),
                    codec,
                    updated_at,
                ),
            )
            if commit:
                conn.commit()
        return len(data)

    def _sqlite_payload_compression_enabled(self) -> bool:
        return bool(self._config.get("structure_store_sqlite_compression_enabled", True))

    def _encode_sqlite_payload(self, payload: dict) -> tuple[bytes, str]:
        data = dumps_json_bytes(payload)
        if not self._sqlite_payload_compression_enabled():
            return data, "json"
        try:
            min_bytes = int(self._config.get("structure_store_sqlite_compression_min_bytes", 4096) or 4096)
        except Exception:
            min_bytes = 4096
        if len(data) < max(0, min_bytes):
            return data, "json"
        try:
            level = int(self._config.get("structure_store_sqlite_compression_level", 1) or 1)
        except Exception:
            level = 1
        level = max(0, min(9, level))
        compressed = zlib.compress(data, level)
        if len(compressed) >= len(data):
            return data, "json"
        return compressed, "zlib+json"

    @staticmethod
    def _decode_sqlite_payload(data: bytes | bytearray | memoryview | str | None, codec: str = "json") -> Any:
        raw = data.tobytes() if isinstance(data, memoryview) else data
        if str(codec or "json") == "zlib+json" and isinstance(raw, (bytes, bytearray)):
            try:
                raw = zlib.decompress(bytes(raw))
            except Exception:
                return None
        return loads_json_bytes(raw, default=None)

    def _compact_payload_for_persistence(self, payload: dict, *, payload_kind: str) -> dict:
        if not bool(self._config.get("compact_sequence_groups_for_persistence_enabled", True)):
            return payload
        if not isinstance(payload, dict):
            return payload
        if payload_kind == "structure":
            structure = payload.get("structure")
            if isinstance(structure, dict):
                compacted_structure = self._compact_obj_sequence_groups_for_persistence(structure, mark=True)
                if compacted_structure is not structure:
                    compacted = dict(payload)
                    compacted["structure"] = compacted_structure
                    return compacted
            return payload
        if payload_kind == "structure_db":
            compacted: dict | None = None
            for table_key in ("diff_table", "group_table", "group_residual_table", "group_memory_table"):
                table = payload.get(table_key)
                if isinstance(table, list):
                    compacted_table = None
                    next_table = []
                    for entry in table:
                        compacted_entry = self._compact_obj_sequence_groups_for_persistence(entry, mark=True)
                        if compacted_entry is not entry:
                            compacted_table = True
                        next_table.append(compacted_entry)
                    if compacted_table:
                        if compacted is None:
                            compacted = dict(payload)
                        compacted[table_key] = next_table
            return compacted if compacted is not None else payload
        return compacted

    def _compact_obj_sequence_groups_for_persistence(self, obj: Any, *, mark: bool = False) -> Any:
        if not isinstance(obj, dict):
            return obj
        compacted: dict | None = None
        compacted_any = False
        for key in ("sequence_groups", "canonical_sequence_groups", "raw_sequence_groups"):
            groups = obj.get(key)
            if isinstance(groups, list):
                compacted_groups = self._compact_sequence_groups_for_persistence(groups)
                if compacted_groups is not groups:
                    if compacted is None:
                        compacted = dict(obj)
                    compacted[key] = compacted_groups
                    compacted_any = True
        if mark and compacted_any:
            if compacted is None:
                compacted = dict(obj)
            meta = dict(compacted.get("storage_compaction", {}) or {})
            meta["sequence_groups_compacted"] = True
            meta["mode"] = "drop_runtime_normalization_cache"
            compacted["storage_compaction"] = meta
        return compacted if compacted is not None else obj

    @classmethod
    def _compact_sequence_groups_for_persistence(cls, groups: list) -> list:
        changed = False
        compacted: list = []
        for group in groups:
            if not isinstance(group, dict):
                compacted.append(group)
                continue
            next_group = dict(group)
            if next_group.pop("_cut_engine_normalized", None) is not None:
                changed = True
            units = next_group.get("units")
            if isinstance(units, list):
                next_units = []
                for unit in units:
                    if not isinstance(unit, dict):
                        next_units.append(unit)
                        continue
                    next_unit = dict(unit)
                    if next_unit.pop("_cut_engine_unit_normalized", None) is not None:
                        changed = True
                    next_units.append(next_unit)
                next_group["units"] = next_units
            compacted.append(next_group)
        return compacted if changed else groups

    def _schedule_structure_persist(self, structure_id: str) -> None:
        if not structure_id or structure_id not in self._structures:
            return
        if self.is_persistence_batching:
            self._dirty_structure_ids.add(structure_id)
            return
        self._persist_structure(self._structures[structure_id])

    def _schedule_db_persist(self, structure_db_id: str) -> None:
        if not structure_db_id or structure_db_id not in self._structure_dbs:
            return
        if self.is_persistence_batching:
            self._dirty_db_ids.add(structure_db_id)
            return
        self._persist_db(self._structure_dbs[structure_db_id])

    def _load(self) -> None:
        if self._storage_backend == "sqlite":
            self._load_sqlite()
            if (
                not self._structures
                and bool(self._config.get("structure_store_sqlite_import_legacy_json_on_empty_enabled", True))
                and list_json_files(self._structures_dir)
            ):
                self._load_filesystem_json()
                self._dirty_structure_ids.update(str(structure_id) for structure_id in self._structures.keys())
                self._dirty_db_ids.update(str(structure_db_id) for structure_db_id in self._structure_dbs.keys())
                self.flush_pending_persistence()
            return
        self._load_filesystem_json()

    def _load_filesystem_json(self) -> None:
        referenced_db_ids: set[str] = set()
        for path in list_json_files(self._structures_dir):
            payload = load_json_file(path, default=None)
            if not isinstance(payload, dict) or not payload.get("id"):
                continue
            structure_id = payload["id"]
            self._structures[structure_id] = payload
            self._recent_structure_ids.append(structure_id)
            structure_db_id = str(payload.get("db_pointer", {}).get("structure_db_id", ""))
            if structure_db_id:
                referenced_db_ids.add(structure_db_id)
            numeric_tail = structure_id.rsplit("_", 1)[-1]
            if numeric_tail.isdigit():
                ensure_counter("st", int(numeric_tail))

        for path in list_json_files(self._indexes_dir):
            numeric_tail = path.stem.rsplit("_", 1)[-1]
            if numeric_tail.isdigit():
                ensure_counter("sdb", int(numeric_tail))
            if referenced_db_ids and path.stem not in referenced_db_ids:
                continue
            if self._structures and not referenced_db_ids:
                # Legacy fallback: structure files without db pointers are invalid for
                # current storage, so avoid loading every orphan DB into memory.
                continue
            if not self._structures:
                continue
            payload = load_json_file(path, default=None)
            if not isinstance(payload, dict) or not payload.get("structure_db_id"):
                continue
            structure_db_id = payload["structure_db_id"]
            if referenced_db_ids and structure_db_id not in referenced_db_ids:
                continue
            owner_id = payload.get("owner_structure_id", "")
            if owner_id and owner_id not in self._structures:
                continue
            self._structure_dbs[structure_db_id] = payload
            if owner_id:
                self._owner_to_db[owner_id] = structure_db_id

        for structure_id, structure_obj in self._structures.items():
            structure_db_id = structure_obj.get("db_pointer", {}).get("structure_db_id", "")
            if structure_db_id and structure_db_id in self._structure_dbs:
                self._owner_to_db.setdefault(structure_id, structure_db_id)
        self._recent_structure_ids.sort(
            key=lambda structure_id: (
                int(self._structures.get(structure_id, {}).get("created_at", 0) or 0),
                str(structure_id),
            )
        )
        self._runtime_revision = 0
        self._structure_lookup_revision = 0

    def _load_sqlite(self) -> None:
        referenced_db_ids: set[str] = set()
        with self._sqlite_lock:
            conn = self._require_sqlite_conn()
            structure_rows = list(conn.execute("SELECT id, payload, codec FROM structures ORDER BY updated_at, id"))
            db_rows = list(conn.execute(
                "SELECT structure_db_id, owner_structure_id, payload, codec FROM structure_dbs"
            ))
        for structure_id, payload_blob, codec in structure_rows:
            payload = self._decode_sqlite_payload(payload_blob, codec)
            if not isinstance(payload, dict) or not payload.get("id"):
                continue
            loaded_id = str(payload.get("id") or structure_id)
            self._structures[loaded_id] = payload
            self._recent_structure_ids.append(loaded_id)
            structure_db_id = str(payload.get("db_pointer", {}).get("structure_db_id", "") or "")
            if structure_db_id:
                referenced_db_ids.add(structure_db_id)
            numeric_tail = loaded_id.rsplit("_", 1)[-1]
            if numeric_tail.isdigit():
                ensure_counter("st", int(numeric_tail))

        for structure_db_id, owner_id, payload_blob, codec in db_rows:
            numeric_tail = str(structure_db_id).rsplit("_", 1)[-1]
            if numeric_tail.isdigit():
                ensure_counter("sdb", int(numeric_tail))
            if not self._structures:
                continue
            if referenced_db_ids and str(structure_db_id) not in referenced_db_ids:
                continue
            if self._structures and not referenced_db_ids:
                continue
            payload = self._decode_sqlite_payload(payload_blob, codec)
            if not isinstance(payload, dict) or not payload.get("structure_db_id"):
                continue
            loaded_db_id = str(payload.get("structure_db_id") or structure_db_id)
            if referenced_db_ids and loaded_db_id not in referenced_db_ids:
                continue
            loaded_owner_id = str(payload.get("owner_structure_id", "") or owner_id or "")
            if loaded_owner_id and loaded_owner_id not in self._structures:
                continue
            self._structure_dbs[loaded_db_id] = payload
            if loaded_owner_id:
                self._owner_to_db[loaded_owner_id] = loaded_db_id

        for structure_id, structure_obj in self._structures.items():
            structure_db_id = structure_obj.get("db_pointer", {}).get("structure_db_id", "")
            if structure_db_id and structure_db_id in self._structure_dbs:
                self._owner_to_db.setdefault(structure_id, structure_db_id)
        self._recent_structure_ids.sort(
            key=lambda structure_id: (
                int(self._structures.get(structure_id, {}).get("created_at", 0) or 0),
                str(structure_id),
            )
        )
        self._runtime_revision = 0
        self._structure_lookup_revision = 0

    def make_runtime_object(
        self,
        structure_id: str,
        er: float,
        ev: float,
        reason: str = "",
        *,
        structure_obj: dict | None = None,
    ) -> dict | None:
        structure_obj = structure_obj if isinstance(structure_obj, dict) else self.get(structure_id)
        if structure_obj is None:
            return None
        structure = structure_obj.get("structure", {}) if isinstance(structure_obj.get("structure", {}), dict) else {}
        display_text = str(structure.get("display_text", structure_id) or structure_id)
        flat_tokens = [str(token) for token in (structure.get("flat_tokens", []) or []) if str(token)]
        plain_text = "".join(flat_tokens) if flat_tokens else ""
        if not plain_text and isinstance(structure.get("sequence_groups", []), list):
            plain_parts = []
            for group in structure.get("sequence_groups", []):
                if not isinstance(group, dict):
                    continue
                if bool(group.get("order_sensitive", False)) and str(group.get("string_unit_kind", "") or "") == "char_sequence":
                    text_part = str(group.get("string_token_text", "") or "")
                    if text_part:
                        plain_parts.append(text_part)
            plain_text = "".join(part for part in plain_parts if part)
        canonical_text = plain_text or structure_id
        return {
            "id": structure_id,
            "object_type": "st",
            "sub_type": structure_obj.get("sub_type", "stimulus_sequence_structure"),
            "content": {
                "raw": canonical_text,
                "display": display_text,
                "normalized": canonical_text,
            },
            "energy": {
                "er": round(float(er), 6),
                "ev": round(float(ev), 6),
            },
            "structure": structure_obj.get("structure", {}),
            "db_pointer": structure_obj.get("db_pointer", {}),
            "source": {
                "module": __module_name__,
                "interface": "make_runtime_object",
                "origin": reason or "hdb_projection",
                "origin_id": structure_id,
                "parent_ids": list(structure_obj.get("source", {}).get("parent_ids", [])),
            },
            "created_at": structure_obj.get("created_at", int(time.time() * 1000)),
            "updated_at": int(time.time() * 1000),
        }





