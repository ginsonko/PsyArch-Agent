# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest
from pathlib import Path

from hdb import HDB


class TestHdbRecencyConfigPropagation(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_recency_config_")
        self.hdb = HDB(
            config_override={
                "data_dir": self.temp_dir,
                "enable_background_repair": False,
                "recency_gain_peak": 7.0,
            }
        )

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_new_structure_and_group_use_hdb_recency_peak(self):
        structure, _ = self.hdb._structure_store.create_structure(
            structure_payload={
                "display_text": "新结构",
                "flat_tokens": ["新结构"],
                "content_signature": "U[F:新结构]",
                "semantic_signature": "st|新结构",
            },
            trace_id="create_structure_peak",
        )
        self.assertAlmostEqual(float(structure["stats"]["recent_gain"]), 7.0, places=6)

        group = self.hdb._group_store.create_group(
            required_structure_ids=[structure["id"]],
            avg_energy_profile={"er": 1.0, "ev": 0.0},
            trace_id="create_group_peak",
        )
        self.assertAlmostEqual(float(group["stats"]["recent_gain"]), 7.0, places=6)

    def test_reload_config_updates_store_side_recency_defaults(self):
        config_path = Path(self.temp_dir) / "reload_peak.yaml"
        config_path.write_text("recency_gain_peak: 9.0\n", encoding="utf-8")

        result = self.hdb.reload_config(trace_id="reload_peak", config_path=str(config_path))
        self.assertTrue(result["success"])

        structure, _ = self.hdb._structure_store.create_structure(
            structure_payload={
                "display_text": "重载结构",
                "flat_tokens": ["重载结构"],
                "content_signature": "U[F:重载结构]",
                "semantic_signature": "st|重载结构",
            },
            trace_id="create_structure_after_reload",
        )
        self.assertAlmostEqual(float(structure["stats"]["recent_gain"]), 9.0, places=6)


if __name__ == "__main__":
    unittest.main()
