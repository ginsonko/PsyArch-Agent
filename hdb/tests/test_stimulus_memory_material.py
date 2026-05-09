# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestStimulusMemoryMaterial(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_stimulus_memory_material_")
        self.hdb = HDB(config_override={"data_dir": self.temp_dir, "enable_background_repair": False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _single_group(*, token: str, unit_id: str) -> list[dict]:
        return [
            {
                "group_index": 0,
                "source_type": "text",
                "origin_frame_id": "frame_0",
                "units": [
                    {
                        "unit_id": unit_id,
                        "token": token,
                        "display_text": token,
                        "unit_role": "feature",
                        "sequence_index": 0,
                        "group_index": 0,
                        "source_group_index": 0,
                        "source_type": "text",
                        "origin_frame_id": "frame_0",
                        "display_visible": True,
                        "er": 1.0,
                        "ev": 0.2,
                    }
                ],
                "csa_bundles": [],
                "tokens": [token],
                "display_text": token,
            }
        ]

    def _create_structure(self, display_text: str) -> dict:
        payload = {
            "display_text": display_text,
            "grouped_display_text": display_text,
            "flat_tokens": [display_text],
            "sequence_groups": self._single_group(token=display_text, unit_id=f"sa_{display_text}"),
            "content_signature": display_text,
            "base_weight": 1.0,
        }
        structure_obj, _ = self.hdb._structure_store.create_structure(
            structure_payload=payload,
            trace_id="test_trace",
            tick_id="test_tick",
            origin="unit_test",
            origin_id=f"structure_{display_text}",
            parent_ids=[],
        )
        return structure_obj

    def test_stimulus_memory_material_keeps_structure_refs_and_items(self):
        structure_a = self._create_structure("你好")
        structure_b = self._create_structure("天气")
        profile = self.hdb._cut.build_sequence_profile_from_groups(
            self._single_group(token="你好", unit_id="sa_input_0")
            + [
                {
                    "group_index": 1,
                    "source_type": "text",
                    "origin_frame_id": "frame_1",
                    "units": [
                        {
                            "unit_id": "sa_input_1",
                            "token": "天气",
                            "display_text": "天气",
                            "unit_role": "feature",
                            "sequence_index": 0,
                            "group_index": 1,
                            "source_group_index": 1,
                            "source_type": "text",
                            "origin_frame_id": "frame_1",
                            "display_visible": True,
                            "er": 0.8,
                            "ev": 0.1,
                        }
                    ],
                    "csa_bundles": [],
                    "tokens": ["天气"],
                    "display_text": "天气",
                }
            ]
        )

        material = self.hdb._stimulus._build_stimulus_memory_material(
            profile=profile,
            structure_ids=[structure_a["id"], structure_b["id"]],
            structure_store=self.hdb._structure_store,
        )

        self.assertEqual(material.get("memory_kind"), "stimulus_packet")
        self.assertEqual(material.get("structure_refs"), [structure_a["id"], structure_b["id"]])
        self.assertEqual(len(material.get("structure_items", [])), 2)
        self.assertIn(structure_a["id"], material.get("structure_energy_profile", {}))
        self.assertIn(structure_b["id"], material.get("structure_energy_profile", {}))
        self.assertGreater(sum(float(v) for v in material.get("structure_energy_profile", {}).values()), 0.0)

    def test_stimulus_memory_material_can_reuse_runtime_projection_energy_for_structure_weights(self):
        structure_a = self._create_structure("你好")
        structure_b = self._create_structure("天气")
        profile = self.hdb._cut.build_sequence_profile_from_groups(self._single_group(token="你好", unit_id="sa_input_0"))

        material = self.hdb._stimulus._build_stimulus_memory_material(
            profile=profile,
            structure_ids=[structure_a["id"], structure_b["id"]],
            structure_store=self.hdb._structure_store,
            runtime_projection_structures=[
                {"structure_id": structure_a["id"], "er": 1.8, "ev": 0.2},
                {"structure_id": structure_a["id"], "er": 0.4, "ev": 0.1},
                {"structure_id": structure_b["id"], "er": 0.2, "ev": 0.0},
            ],
        )

        weights = material.get("structure_energy_profile", {})
        self.assertGreater(float(weights.get(structure_a["id"], 0.0)), float(weights.get(structure_b["id"], 0.0)))
        self.assertAlmostEqual(sum(float(v) for v in weights.values()), 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
