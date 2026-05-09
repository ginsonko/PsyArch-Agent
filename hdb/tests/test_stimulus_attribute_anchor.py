# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestStimulusAttributeAnchor(unittest.TestCase):
    """
    Regression test:

    In the theory, an attribute SA can also become an anchor for stimulus-level retrieval,
    even when that attribute unit is "display-hidden" (display_visible=false) in group.tokens.

    Previously, StimulusRetrievalEngine used profile.flat_tokens (derived from group.tokens)
    as a hard prerequisite for anchor containment, which incorrectly filtered out valid
    candidates when anchor_token is an attribute token.
    """

    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_attr_anchor_")
        self.hdb = HDB(config_override={"data_dir": self.temp_dir, "enable_background_repair": False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @staticmethod
    def _csa_group(*, feature_token: str, attribute_token: str) -> dict:
        units = [
            {
                "unit_id": "sa_feature",
                "token": feature_token,
                "display_text": feature_token,
                "unit_role": "feature",
                "sequence_index": 0,
                "group_index": 0,
                "source_group_index": 0,
                "source_type": "text",
                "origin_frame_id": "frame_0",
                "display_visible": True,
                "er": 1.0,
                "ev": 0.0,
            },
            {
                "unit_id": "sa_attribute",
                "token": attribute_token,
                "display_text": attribute_token,
                "unit_role": "attribute",
                "sequence_index": 1,
                "group_index": 0,
                "source_group_index": 0,
                "source_type": "text",
                "origin_frame_id": "frame_0",
                "display_visible": False,
                "er": 0.6,
                "ev": 0.0,
                # Anchor binding hint (also used when bundles are inferred).
                "bundle_anchor_unit_id": "sa_feature",
                "attribute_name": "颜色",
                "attribute_value": attribute_token,
            },
        ]
        return {
            "group_index": 0,
            "source_type": "text",
            "origin_frame_id": "frame_0",
            "units": units,
            "csa_bundles": [
                {
                    "bundle_id": "bundle_0",
                    "anchor_unit_id": "sa_feature",
                    "member_unit_ids": ["sa_feature", "sa_attribute"],
                }
            ],
        }

    def test_attribute_anchor_can_match_structure_even_when_flat_tokens_hide_attribute(self):
        cut = self.hdb._cut
        structure_store = self.hdb._structure_store
        pointer_index = self.hdb._pointer_index
        stimulus = self.hdb._stimulus

        groups = [self._csa_group(feature_token="苹果", attribute_token="红色")]
        profile = cut.build_sequence_profile_from_groups(groups)

        # Create a structure that has BOTH feature+attribute units, but only the feature token is in flat_tokens.
        payload = cut.make_structure_payload_from_profile(profile, confidence=0.9, ext={"kind": "test_attr_anchor"})
        structure_obj, _ = structure_store.create_structure(
            structure_payload=payload,
            trace_id="test_trace",
            tick_id="test_tick",
            origin="unit_test",
            origin_id="test_attr_anchor",
            parent_ids=[],
        )
        pointer_index.register_structure(structure_obj)

        existing_profile = stimulus._build_structure_profile(
            structure_obj=structure_obj,
            structure_store=structure_store,
            cut_engine=cut,
        )
        # The attribute token is intentionally hidden from flat_tokens when the group has visible feature units.
        self.assertIn("苹果", list(existing_profile.get("flat_tokens", [])))
        self.assertNotIn("红色", list(existing_profile.get("flat_tokens", [])))

        incoming_profile = cut.build_sequence_profile_from_groups(groups)
        incoming_units = [
            dict(unit)
            for group in incoming_profile.get("sequence_groups", [])
            for unit in group.get("units", [])
            if isinstance(unit, dict)
        ]

        best, details = stimulus._best_structure_match(
            incoming_profile=incoming_profile,
            competition_units=incoming_units,
            candidates=[structure_obj],
            structure_store=structure_store,
            cut_engine=cut,
            anchor_token="红色",
            min_existing_length=1,
        )

        self.assertIsNotNone(best)
        self.assertEqual(best.get("structure_id", ""), structure_obj.get("id", ""))
        self.assertTrue(any(d.get("contains_anchor") for d in details if d.get("structure_id") == structure_obj.get("id")))


if __name__ == "__main__":
    unittest.main()

