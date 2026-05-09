# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestMemoryActivationStore(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_memory_activation_")
        self.hdb = HDB(
            config_override={
                "data_dir": self.temp_dir,
                "enable_background_repair": False,
                "memory_activation_decay_round_ratio_ev": 0.5,
                "memory_activation_prune_threshold_ev": 0.3,
                "memory_activation_event_history_limit": 4,
            }
        )

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _append_memory(self, summary: str, extra_payload: dict | None = None) -> str:
        payload = {
            "event_summary": summary,
            "structure_refs": [],
            "group_refs": [],
        }
        if extra_payload:
            payload.update(extra_payload)
        result = self.hdb.append_episodic_memory(
            episodic_payload=payload,
            trace_id=f"append_{summary}",
        )
        self.assertTrue(result["success"])
        return result["data"]["episodic_id"]

    def test_memory_activation_pool_decays_and_prunes(self):
        memory_id = self._append_memory("decay_case")
        result = self.hdb.apply_memory_activation_targets(
            targets=[
                {
                    "projection_kind": "memory",
                    "memory_id": memory_id,
                    "target_display_text": "decay_case",
                    "delta_er": 0.8,
                    "delta_ev": 1.0,
                    "sources": ["st_decay"],
                    "modes": ["er_induction"],
                }
            ],
            trace_id="apply_decay_case",
        )
        self.assertTrue(result["success"])
        self.assertAlmostEqual(result["data"]["total_delta_er"], 0.8, places=6)
        self.assertAlmostEqual(result["data"]["total_delta_ev"], 1.0, places=6)

        tick_one = self.hdb.tick_memory_activation_pool(trace_id="tick_one")
        self.assertTrue(tick_one["success"])
        self.assertAlmostEqual(tick_one["data"]["total_er_after"], 0.4, places=6)
        self.assertAlmostEqual(tick_one["data"]["total_ev_after"], 0.5, places=6)
        snapshot_one = self.hdb.get_memory_activation_snapshot(trace_id="snapshot_one", limit=8)
        self.assertEqual(snapshot_one["data"]["summary"]["count"], 1)
        self.assertAlmostEqual(snapshot_one["data"]["items"][0]["er"], 0.4, places=6)
        self.assertAlmostEqual(snapshot_one["data"]["items"][0]["ev"], 0.5, places=6)
        self.assertAlmostEqual(snapshot_one["data"]["items"][0]["total_energy"], 0.9, places=6)

        tick_two = self.hdb.tick_memory_activation_pool(trace_id="tick_two")
        self.assertTrue(tick_two["success"])
        self.assertEqual(tick_two["data"]["pruned_count"], 1)
        snapshot_two = self.hdb.get_memory_activation_snapshot(trace_id="snapshot_two", limit=8)
        self.assertEqual(snapshot_two["data"]["summary"]["count"], 0)

    def test_memory_activation_snapshot_supports_recent_sort(self):
        older_memory_id = self._append_memory("older_memory")
        newer_memory_id = self._append_memory("newer_memory")

        self.hdb.apply_memory_activation_targets(
            targets=[
                {
                    "projection_kind": "memory",
                    "memory_id": older_memory_id,
                    "target_display_text": "older_memory",
                    "delta_er": 2.0,
                    "sources": ["st_old"],
                    "modes": ["manual_recall"],
                }
            ],
            trace_id="apply_old",
        )
        self.hdb.apply_memory_activation_targets(
            targets=[
                {
                    "projection_kind": "memory",
                    "memory_id": newer_memory_id,
                    "target_display_text": "newer_memory",
                    "delta_ev": 1.0,
                    "sources": ["st_new"],
                    "modes": ["er_induction"],
                }
            ],
            trace_id="apply_new",
        )

        energy_snapshot = self.hdb.get_memory_activation_snapshot(
            trace_id="memory_snapshot_energy",
            limit=8,
            sort_by="energy_desc",
        )
        recent_snapshot = self.hdb.get_memory_activation_snapshot(
            trace_id="memory_snapshot_recent",
            limit=8,
            sort_by="recent_desc",
        )

        self.assertEqual(energy_snapshot["data"]["items"][0]["memory_id"], older_memory_id)
        self.assertEqual(recent_snapshot["data"]["items"][0]["memory_id"], newer_memory_id)
        self.assertAlmostEqual(energy_snapshot["data"]["summary"]["total_energy"], 3.0, places=6)

    def test_memory_activation_feedback_records_dual_channels(self):
        memory_id = self._append_memory("feedback_case")
        self.hdb.apply_memory_activation_targets(
            targets=[
                {
                    "projection_kind": "memory",
                    "memory_id": memory_id,
                    "target_display_text": "feedback_case",
                    "delta_er": 0.5,
                    "delta_ev": 0.25,
                    "sources": ["st_feedback"],
                    "modes": ["manual_feedback_seed"],
                }
            ],
            trace_id="apply_feedback_case",
        )

        feedback_result = self.hdb.record_memory_feedback(
            feedback_items=[
                {
                    "memory_id": memory_id,
                    "delta_er": 0.3,
                    "delta_ev": 0.4,
                    "feedback_kind": "manual_test",
                    "target_count": 2,
                    "grouped_display_text": "{A} / {B}",
                    "target_display_texts": ["A", "B"],
                }
            ],
            trace_id="record_feedback_case",
        )
        self.assertTrue(feedback_result["success"])
        self.assertAlmostEqual(feedback_result["data"]["total_feedback_er"], 0.3, places=6)
        self.assertAlmostEqual(feedback_result["data"]["total_feedback_ev"], 0.4, places=6)
        item = feedback_result["data"]["items"][0]
        self.assertAlmostEqual(item["last_feedback_er"], 0.3, places=6)
        self.assertAlmostEqual(item["last_feedback_ev"], 0.4, places=6)
        self.assertAlmostEqual(item["total_feedback_er"], 0.3, places=6)
        self.assertAlmostEqual(item["total_feedback_ev"], 0.4, places=6)
        self.assertEqual(item["recent_feedback_events"][-1]["feedback_kind"], "manual_test")


if __name__ == "__main__":
    unittest.main()
