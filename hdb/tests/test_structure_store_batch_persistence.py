# -*- coding: utf-8 -*-

import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from hdb._context_metadata import build_context_metadata
from hdb._structure_store import StructureStore


def _make_payload(text: str) -> dict:
    tokens = [ch for ch in str(text or "")]
    units = [
        {
            "unit_id": f"unit_{idx}",
            "token": token,
            "source_type": "current",
            "display_visible": True,
        }
        for idx, token in enumerate(tokens)
    ]
    return {
        "sub_type": "stimulus_sequence_structure",
        "unit_type": "sa_csa_sequence",
        "display_text": text,
        "member_refs": [],
        "sequence_groups": [
            {
                "group_index": 0,
                "tokens": tokens,
                "units": units,
                "source_type": "current",
                "order_sensitive": True,
            }
        ],
        "flat_tokens": tokens,
        "content_signature": text,
        "semantic_signature": text,
        "base_weight": 1.0,
        "meta": {
            "confidence": 0.9,
            "field_registry_version": "test",
            "debug": {},
            "ext": {},
        },
        "ext": {},
    }


class TestStructureStoreBatchPersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="structure_store_batch_"))
        self.structures_dir = self.temp_dir / "structures"
        self.indexes_dir = self.temp_dir / "indexes"
        self.store = StructureStore(self.structures_dir, self.indexes_dir, config={})

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_structure_flushes_at_batch_end(self):
        with self.store.batch_persistence():
            structure_obj, structure_db = self.store.create_structure(
                structure_payload=_make_payload("你好"),
                trace_id="batch_create",
                tick_id="batch_create",
                origin="test",
                origin_id="test",
                parent_ids=[],
            )
            self.assertFalse(self.store._structure_file_path(structure_obj["id"]).exists())
            self.assertFalse(self.store._db_file_path(structure_db["structure_db_id"]).exists())

        self.assertTrue(self.store._structure_file_path(structure_obj["id"]).exists())
        self.assertTrue(self.store._db_file_path(structure_db["structure_db_id"]).exists())

    def test_add_diff_entry_keeps_disk_snapshot_stale_until_flush(self):
        owner_obj, owner_db = self.store.create_structure(
            structure_payload=_make_payload("你好"),
            trace_id="owner_create",
            tick_id="owner_create",
            origin="test",
            origin_id="owner",
            parent_ids=[],
        )
        target_obj, _ = self.store.create_structure(
            structure_payload=_make_payload("你好啊"),
            trace_id="target_create",
            tick_id="target_create",
            origin="test",
            origin_id="target",
            parent_ids=[],
        )
        owner_db_path = self.store._db_file_path(owner_db["structure_db_id"])
        baseline = json.loads(owner_db_path.read_text(encoding="utf-8"))
        self.assertEqual(baseline.get("diff_table", []), [])

        with self.store.batch_persistence():
            entry = self.store.add_diff_entry(
                owner_obj["id"],
                target_id=target_obj["id"],
                content_signature=target_obj.get("structure", {}).get("content_signature", ""),
                base_weight=0.7,
                residual_existing_signature="",
                residual_incoming_signature="啊",
                ext={"relation_type": "incoming_extension"},
            )
            self.assertIsNotNone(entry)
            in_memory = self.store.get_db_by_owner(owner_obj["id"])
            self.assertEqual(len(in_memory.get("diff_table", [])), 1)
            disk_payload = json.loads(owner_db_path.read_text(encoding="utf-8"))
            self.assertEqual(disk_payload.get("diff_table", []), [])

        flushed = json.loads(owner_db_path.read_text(encoding="utf-8"))
        self.assertEqual(len(flushed.get("diff_table", [])), 1)
        self.assertEqual(flushed["diff_table"][0]["target_id"], target_obj["id"])

    def test_runtime_context_summary_tracks_structure_and_diff_updates_incrementally(self):
        owner_payload = _make_payload("好")
        owner_context = build_context_metadata(
            context_owner_structure_id="st_ctx_a",
            context_ref_object_id="st_ctx_a",
            context_path_ids=["st_ctx_a"],
        )
        owner_payload["ext"] = dict(owner_context)
        owner_payload["meta"]["ext"] = dict(owner_context)
        alt_payload = _make_payload("好")
        alt_context = build_context_metadata(
            context_owner_structure_id="st_ctx_b",
            context_ref_object_id="st_ctx_b",
            context_path_ids=["st_ctx_a", "st_ctx_b"],
        )
        alt_payload["ext"] = dict(alt_context)
        alt_payload["meta"]["ext"] = dict(alt_context)
        target_payload = _make_payload("呀")

        owner_obj, _ = self.store.create_structure(
            structure_payload=owner_payload,
            trace_id="ctx_owner",
            tick_id="ctx_owner",
            origin="test",
            origin_id="ctx_owner",
            parent_ids=[],
        )
        _, _ = self.store.create_structure(
            structure_payload=alt_payload,
            trace_id="ctx_alt",
            tick_id="ctx_alt",
            origin="test",
            origin_id="ctx_alt",
            parent_ids=[],
        )
        target_obj, _ = self.store.create_structure(
            structure_payload=target_payload,
            trace_id="ctx_target",
            tick_id="ctx_target",
            origin="test",
            origin_id="ctx_target",
            parent_ids=[],
        )

        summary = self.store.get_runtime_context_summary()
        self.assertEqual(summary.get("contextual_structure_count"), 2)
        self.assertEqual(summary.get("multi_context_structure_count"), 1)
        self.assertEqual(summary.get("same_content_multi_context_count"), 1)
        self.assertAlmostEqual(float(summary.get("structure_context_path_depth_mean", 0.0) or 0.0), 1.5, places=6)

        self.store.add_diff_entry(
            owner_obj["id"],
            target_id=target_obj["id"],
            content_signature=target_obj.get("structure", {}).get("content_signature", ""),
            base_weight=0.7,
            residual_existing_signature="",
            residual_incoming_signature="呀",
            ext={
                "relation_type": "residual_context",
                "context_ref_object_id": "st_ctx_branch",
                "context_ref_object_type": "st",
                "context_path_ids": [owner_obj["id"], "st_ctx_branch"],
            },
        )
        self.store.add_diff_entry(
            owner_obj["id"],
            target_id=target_obj["id"],
            content_signature=target_obj.get("structure", {}).get("content_signature", ""),
            base_weight=0.7,
            residual_existing_signature="",
            residual_incoming_signature="呀_2",
            ext={"relation_type": "incoming_extension"},
        )

        summary = self.store.get_runtime_context_summary()
        self.assertEqual(summary.get("diff_entry_count"), 2)
        self.assertEqual(summary.get("contextual_diff_entry_count"), 1)
        self.assertEqual(summary.get("residual_diff_entry_count"), 2)


class TestStructureStoreSqlitePersistence(unittest.TestCase):
    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="structure_store_sqlite_"))
        self.structures_dir = self.temp_dir / "structures"
        self.indexes_dir = self.temp_dir / "indexes"
        self.config = {
            "structure_store_backend": "sqlite",
            "structure_store_sqlite_path": str(self.temp_dir / "hdb_structure_store.sqlite3"),
        }
        self.store = StructureStore(self.structures_dir, self.indexes_dir, config=self.config)

    def tearDown(self):
        try:
            self.store.close()
        except Exception:
            pass
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_sqlite_backend_persists_and_reloads_structure_and_owner_db(self):
        with self.store.batch_persistence(flush=False):
            owner_obj, owner_db = self.store.create_structure(
                structure_payload=_make_payload("早上好"),
                trace_id="sqlite_owner",
                tick_id="sqlite_owner",
                origin="test",
                origin_id="owner",
                parent_ids=[],
            )
            target_obj, _ = self.store.create_structure(
                structure_payload=_make_payload("早上好继续"),
                trace_id="sqlite_target",
                tick_id="sqlite_target",
                origin="test",
                origin_id="target",
                parent_ids=[],
            )
            entry = self.store.add_diff_entry(
                owner_obj["id"],
                target_id=target_obj["id"],
                content_signature=target_obj.get("structure", {}).get("content_signature", ""),
                base_weight=0.8,
                residual_existing_signature="",
                residual_incoming_signature="继续",
                ext={"relation_type": "incoming_extension"},
            )
            self.assertIsNotNone(entry)

        self.assertIsNotNone(self.store.get(owner_obj["id"]))
        self.assertEqual(len(self.store.get_db_by_owner(owner_obj["id"]).get("diff_table", [])), 1)
        self.assertFalse(self.store._structure_file_path(owner_obj["id"]).exists())
        self.assertFalse(self.store._db_file_path(owner_db["structure_db_id"]).exists())

        flush = self.store.flush_pending_persistence()
        self.assertEqual(flush.get("backend"), "sqlite")
        self.assertEqual(flush.get("structure_count"), 2)
        self.assertGreaterEqual(flush.get("db_count"), 2)
        self.store.close()

        reloaded = StructureStore(self.structures_dir, self.indexes_dir, config=self.config)
        try:
            reloaded_owner = reloaded.get(owner_obj["id"])
            self.assertIsNotNone(reloaded_owner)
            self.assertEqual(reloaded_owner.get("structure", {}).get("display_text"), "早上好")
            reloaded_db = reloaded.get_db_by_owner(owner_obj["id"])
            self.assertIsNotNone(reloaded_db)
            self.assertEqual(len(reloaded_db.get("diff_table", [])), 1)
            self.assertEqual(reloaded_db["diff_table"][0]["target_id"], target_obj["id"])
        finally:
            reloaded.close()

    def test_sqlite_clear_removes_rows_and_runtime_indexes(self):
        structure_obj, _ = self.store.create_structure(
            structure_payload=_make_payload("清空测试"),
            trace_id="sqlite_clear",
            tick_id="sqlite_clear",
            origin="test",
            origin_id="clear",
            parent_ids=[],
        )
        self.assertIsNotNone(self.store.get(structure_obj["id"]))
        result = self.store.clear_structures()
        self.assertEqual(result.get("structure_count"), 1)
        self.assertEqual(self.store.structure_count, 0)
        self.assertEqual(self.store.structure_db_count, 0)
        self.store.close()

        reloaded = StructureStore(self.structures_dir, self.indexes_dir, config=self.config)
        try:
            self.assertEqual(reloaded.structure_count, 0)
            self.assertEqual(reloaded.structure_db_count, 0)
        finally:
            reloaded.close()

    def test_sqlite_empty_store_imports_legacy_files_once(self):
        legacy_dir = self.temp_dir / "legacy"
        legacy_structures = legacy_dir / "structures"
        legacy_indexes = legacy_dir / "indexes"
        legacy_store = StructureStore(legacy_structures, legacy_indexes, config={})
        try:
            legacy_obj, legacy_db = legacy_store.create_structure(
                structure_payload=_make_payload("旧库导入"),
                trace_id="legacy_create",
                tick_id="legacy_create",
                origin="test",
                origin_id="legacy",
                parent_ids=[],
            )
        finally:
            legacy_store.close()

        sqlite_config = {
            "structure_store_backend": "sqlite",
            "structure_store_sqlite_path": str(legacy_dir / "hdb_structure_store.sqlite3"),
            "structure_store_sqlite_import_legacy_json_on_empty_enabled": True,
        }
        sqlite_store = StructureStore(legacy_structures, legacy_indexes, config=sqlite_config)
        try:
            self.assertIsNotNone(sqlite_store.get(legacy_obj["id"]))
            self.assertIsNotNone(sqlite_store.get_db_by_owner(legacy_obj["id"]))
            self.assertEqual(sqlite_store.structure_count, 1)
            self.assertEqual(sqlite_store.structure_db_count, 1)
            self.assertTrue((legacy_dir / "hdb_structure_store.sqlite3").exists())
        finally:
            sqlite_store.close()

        reloaded = StructureStore(legacy_structures, legacy_indexes, config=sqlite_config)
        try:
            self.assertIsNotNone(reloaded.get(legacy_obj["id"]))
            self.assertEqual(reloaded.get_db_by_owner(legacy_obj["id"])["structure_db_id"], legacy_db["structure_db_id"])
        finally:
            reloaded.close()

    def test_sqlite_backend_accepts_flush_from_worker_thread(self):
        owner_obj, owner_db = self.store.create_structure(
            structure_payload=_make_payload("跨线程"),
            trace_id="sqlite_thread_owner",
            tick_id="sqlite_thread_owner",
            origin="test",
            origin_id="thread_owner",
            parent_ids=[],
        )
        self.store.update_structure(owner_obj)
        self.store.update_db(owner_db)
        errors: list[BaseException] = []

        def worker() -> None:
            try:
                self.store.flush_pending_persistence()
            except BaseException as exc:  # pragma: no cover - assertion reports exact worker error.
                errors.append(exc)

        thread = threading.Thread(target=worker)
        thread.start()
        thread.join(timeout=10)
        self.assertFalse(thread.is_alive())
        self.assertEqual(errors, [])
