# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


def _packet(text: str, *, packet_id: str) -> dict:
    sa_items = []
    for idx, ch in enumerate(text):
        sa_items.append(
            {
                "id": f"{packet_id}_sa_{idx}",
                "object_type": "sa",
                "content": {"raw": ch, "display": ch, "normalized": ch},
                "stimulus": {"role": "feature", "modality": "text"},
                "energy": {"er": 1.0, "ev": 0.0},
                "ext": {"packet_context": {"sequence_index": idx}},
            }
        )
    return {
        "id": packet_id,
        "object_type": "stimulus_packet",
        "sa_items": sa_items,
        "csa_items": [],
        "grouped_sa_sequences": [
            {
                "group_index": 0,
                "source_type": "current",
                "origin_frame_id": f"frame_{packet_id}",
                "sa_ids": [item["id"] for item in sa_items],
                "csa_ids": [],
            }
        ],
        "energy_summary": {"current_total_er": float(len(sa_items)), "current_total_ev": 0.0},
        "source": {"parent_ids": []},
    }


class TestHdbSnapshotContextResidualCounts(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_snapshot_")
        self.hdb = HDB(config_override={"data_dir": self.temp_dir, "enable_background_repair": False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _store_packet_as_structure(self, text: str, *, trace_id: str) -> dict:
        packet = _packet(text, packet_id=trace_id)
        profile = self.hdb._cut.build_sequence_profile_from_stimulus_packet(packet)
        payload = self.hdb._cut.make_structure_payload_from_profile(
            profile,
            confidence=0.9,
            ext={"kind": "test_seed", "relation_type": "test_seed"},
        )
        structure_obj, _ = self.hdb._structure_store.create_structure(
            structure_payload=payload,
            trace_id=trace_id,
            tick_id=trace_id,
            origin="test_seed",
            origin_id=packet["id"],
            parent_ids=[],
        )
        self.hdb._pointer_index.register_structure(structure_obj)
        return structure_obj

    def test_snapshot_distinguishes_contextual_vs_residual_diff_entries(self):
        owner = self._store_packet_as_structure("你好", trace_id="owner")
        target_a = self._store_packet_as_structure("你好啊", trace_id="target_a")
        target_b = self._store_packet_as_structure("你好呀", trace_id="target_b")
        target_c = self._store_packet_as_structure("你好呢", trace_id="target_c")

        self.hdb._structure_store.add_diff_entry(
            owner["id"],
            target_id=target_a["id"],
            content_signature=target_a["structure"]["content_signature"],
            base_weight=0.7,
            residual_existing_signature="",
            residual_incoming_signature="啊",
            ext={"relation_type": "incoming_extension"},
        )
        self.hdb._structure_store.add_diff_entry(
            owner["id"],
            target_id=target_b["id"],
            content_signature=target_b["structure"]["content_signature"],
            base_weight=0.7,
            residual_existing_signature="",
            residual_incoming_signature="呀",
            ext={
                "relation_type": "atomic_anchor",
                "context_ref_object_id": "sa_ctx_anchor",
                "context_ref_object_type": "sa",
            },
        )
        self.hdb._structure_store.add_diff_entry(
            owner["id"],
            target_id=target_c["id"],
            content_signature=target_c["structure"]["content_signature"],
            base_weight=0.7,
            residual_existing_signature="",
            residual_incoming_signature="呢",
            ext={
                "relation_type": "residual_context",
                "context_ref_object_id": "st_ctx_branch",
                "context_ref_object_type": "st",
                "context_path_ids": [owner["id"], "st_ctx_branch"],
            },
        )

        snapshot = self.hdb._snapshot.build_hdb_snapshot(
            trace_id="snapshot_trace",
            structure_store=self.hdb._structure_store,
            group_store=self.hdb._group_store,
            episodic_store=self.hdb._episodic_store,
            memory_activation_store=self.hdb._memory_activation_store,
            pointer_index=self.hdb._pointer_index,
            issue_queue=[],
            repair_jobs={},
        )
        summary = snapshot.get("summary", {})

        self.assertEqual(summary.get("diff_entry_count"), 3)
        self.assertEqual(summary.get("contextual_diff_entry_count"), 2)
        self.assertEqual(summary.get("residual_diff_entry_count"), 2)

    def test_recent_indexes_and_snapshot_summary_do_not_require_full_scan(self):
        first = self._store_packet_as_structure("甲", trace_id="recent_a")
        second = self._store_packet_as_structure("乙", trace_id="recent_b")
        third = self._store_packet_as_structure("丙", trace_id="recent_c")

        recent_ids = [item.get("id", "") for item in self.hdb._structure_store.get_recent_structures(limit=2)]
        self.assertEqual(recent_ids, [third["id"], second["id"]])
        self.assertNotIn(first["id"], recent_ids)

        def fail_iter_structures():
            raise AssertionError("snapshot should use runtime summary instead of full structure scan")

        def fail_iter_structure_dbs():
            raise AssertionError("snapshot should use runtime summary instead of full DB scan")

        original_iter_structures = self.hdb._structure_store.iter_structures
        original_iter_structure_dbs = self.hdb._structure_store.iter_structure_dbs
        self.hdb._structure_store.iter_structures = fail_iter_structures
        self.hdb._structure_store.iter_structure_dbs = fail_iter_structure_dbs
        try:
            snapshot = self.hdb._snapshot.build_hdb_snapshot(
                trace_id="snapshot_no_full_scan",
                structure_store=self.hdb._structure_store,
                group_store=self.hdb._group_store,
                episodic_store=self.hdb._episodic_store,
                memory_activation_store=self.hdb._memory_activation_store,
                pointer_index=self.hdb._pointer_index,
                issue_queue=[],
                repair_jobs={},
                top_k=2,
            )
        finally:
            self.hdb._structure_store.iter_structures = original_iter_structures
            self.hdb._structure_store.iter_structure_dbs = original_iter_structure_dbs

        self.assertEqual(snapshot["summary"]["structure_count"], 3)
        self.assertEqual(
            [item.get("structure_id", "") for item in snapshot.get("recent_structures", [])],
            [third["id"], second["id"]],
        )
