# -*- coding: utf-8 -*-

import unittest

from hdb._cut_engine import CutEngine
from hdb._pointer_index import PointerIndex


class TestCutEngine(unittest.TestCase):
    def _csa_group(self, anchor: str, attrs: list[str], *, group_index: int = 0) -> dict:
        units = [
            {
                "unit_id": f"feature_{group_index}_{anchor}",
                "token": anchor,
                "unit_role": "feature",
                "sequence_index": 0,
                "group_index": group_index,
                "source_group_index": group_index,
                "source_type": "text",
                "origin_frame_id": f"frame_{group_index}",
                "display_visible": True,
            }
        ]
        member_ids = [units[0]["unit_id"]]
        for index, attr in enumerate(attrs, start=1):
            unit_id = f"attr_{group_index}_{index}_{attr}"
            units.append(
                {
                    "unit_id": unit_id,
                    "token": attr,
                    "unit_role": "attribute",
                    "sequence_index": index,
                    "group_index": group_index,
                    "source_group_index": group_index,
                    "source_type": "text",
                    "origin_frame_id": f"frame_{group_index}",
                    "display_visible": False,
                    "bundle_anchor_unit_id": units[0]["unit_id"],
                }
            )
            member_ids.append(unit_id)
        return {
            "group_index": group_index,
            "source_type": "text",
            "origin_frame_id": f"frame_{group_index}",
            "units": units,
            "csa_bundles": [
                {
                    "bundle_id": f"bundle_{group_index}_{anchor}",
                    "anchor_unit_id": units[0]["unit_id"],
                    "member_unit_ids": member_ids,
                }
            ],
        }

    def test_maximum_common_part_detects_contiguous_overlap(self):
        engine = CutEngine()
        result = engine.maximum_common_part(['你', '好', '呀'], ['你', '好', '！'])
        self.assertEqual(result['common_tokens'], ['你', '好'])
        self.assertEqual(result['common_length'], 2)
        self.assertEqual(result['residual_existing_tokens'], ['呀'])
        self.assertEqual(result['residual_incoming_tokens'], ['！'])

    def test_full_inclusion_fast_path_does_not_skip_earlier_partial_group(self):
        engine = CutEngine()
        seed = [
            self._csa_group("A", ["x"], group_index=0),
            self._csa_group("B", ["x"], group_index=1),
            self._csa_group("!", ["z"], group_index=2),
        ]
        incoming = [
            self._csa_group("A", ["x"], group_index=0),
            self._csa_group("B", ["x"], group_index=1),
            {
                "group_index": 2,
                "source_type": "text",
                "origin_frame_id": "frame_early_bang",
                "units": [
                    {
                        "unit_id": "feature_early_bang",
                        "token": "!",
                        "unit_role": "feature",
                        "sequence_index": 0,
                        "group_index": 2,
                        "source_group_index": 2,
                        "source_type": "text",
                        "origin_frame_id": "frame_early_bang",
                        "display_visible": True,
                    }
                ],
                "csa_bundles": [],
            },
            self._csa_group("!", ["z"], group_index=3),
        ]

        result = engine.maximum_common_part(seed, incoming)

        self.assertEqual(result["matched_incoming_group_indices"], [0, 1, 2])
        self.assertEqual(result["common_groups"][2]["display_text"], "{!}")
        self.assertNotIn("z", result["common_groups"][2]["display_text"])

    def test_build_internal_packet_preserves_fragment_energy_totals(self):
        engine = CutEngine()
        packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_001",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["A", "B"]},
                        {"group_index": 1, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["C"]},
                    ],
                    "flat_tokens": ["A", "B", "C"],
                    "er_hint": 1.2,
                    "ev_hint": 0.6,
                }
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )
        total_er = sum(item["energy"]["er"] for item in packet["sa_items"])
        total_ev = sum(item["energy"]["ev"] for item in packet["sa_items"])
        self.assertAlmostEqual(total_er, 1.2, places=6)
        self.assertAlmostEqual(total_ev, 0.6, places=6)

    def test_build_internal_packet_collapses_fragment_groups_into_one_cooccurrence_group(self):
        engine = CutEngine()
        packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_001",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["A", "B"]},
                        {"group_index": 1, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["C"]},
                    ],
                    "flat_tokens": ["A", "B", "C"],
                    "er_hint": 1.2,
                    "ev_hint": 0.6,
                },
                {
                    "fragment_id": "frag_002",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_002", "tokens": ["D"]},
                    ],
                    "flat_tokens": ["D"],
                    "er_hint": 0.4,
                    "ev_hint": 0.2,
                },
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )
        self.assertEqual(len(packet["grouped_sa_sequences"]), 1)
        profile = engine.build_sequence_profile_from_stimulus_packet(packet)
        self.assertEqual(len(profile["sequence_groups"]), 1)
        self.assertCountEqual(profile["sequence_groups"][0]["tokens"], ["A", "B", "C", "D"])
        group_ext = packet["grouped_sa_sequences"][0].get("ext", {}) or {}
        self.assertTrue(group_ext.get("flattened_internal_single_group", False))
        self.assertEqual(int(group_ext.get("flattened_source_group_count", 0) or 0), 3)

    def test_build_internal_packet_can_keep_legacy_fragment_groups_when_switch_disabled(self):
        engine = CutEngine({"internal_stimulus_flatten_to_single_cooccurrence_group_enabled": False})
        packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_001",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["A", "B"]},
                        {"group_index": 1, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["C"]},
                    ],
                    "flat_tokens": ["A", "B", "C"],
                    "er_hint": 1.2,
                    "ev_hint": 0.6,
                },
                {
                    "fragment_id": "frag_002",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_002", "tokens": ["D"]},
                    ],
                    "flat_tokens": ["D"],
                    "er_hint": 0.4,
                    "ev_hint": 0.2,
                },
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )
        self.assertEqual(len(packet["grouped_sa_sequences"]), 3)
        profile = engine.build_sequence_profile_from_stimulus_packet(packet)
        self.assertEqual(len(profile["sequence_groups"]), 3)


    def test_build_internal_packet_uses_unique_runtime_csa_ids(self):
        engine = CutEngine()
        left_group = self._csa_group("A", ["x"])
        right_group = self._csa_group("B", ["y"])
        left_group["csa_bundles"][0]["bundle_id"] = "common_bundle_0"
        right_group["csa_bundles"][0]["bundle_id"] = "common_bundle_0"

        packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_001",
                    "sequence_groups": [left_group],
                    "flat_tokens": ["A", "x"],
                    "er_hint": 1.0,
                    "ev_hint": 0.0,
                },
                {
                    "fragment_id": "frag_002",
                    "sequence_groups": [right_group],
                    "flat_tokens": ["B", "y"],
                    "er_hint": 1.0,
                    "ev_hint": 0.0,
                },
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )

        csa_ids = [item["id"] for item in packet["csa_items"]]
        self.assertEqual(len(csa_ids), 2)
        self.assertEqual(len(set(csa_ids)), 2)
        self.assertTrue(all(csa_id.startswith("csa_internal_") for csa_id in csa_ids))

    def test_merge_stimulus_packets_appends_internal_into_last_external_group(self):
        engine = CutEngine()
        external_packet = {
            "id": "spkt_external",
            "object_type": "stimulus_packet",
            "current_frame_id": "spkt_external",
            "echo_frame_ids": [],
            "sa_items": [
                {
                    "id": "sa_echo_0",
                    "object_type": "sa",
                    "content": {"raw": "X", "display": "X", "normalized": "X"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 0.5, "ev": 0.0},
                    "source": {"parent_ids": []},
                    "ext": {"packet_context": {"group_index": 0, "source_group_index": 0, "source_type": "echo", "origin_frame_id": "f0", "sequence_index": 0}},
                },
                {
                    "id": "sa_current_0",
                    "object_type": "sa",
                    "content": {"raw": "Y", "display": "Y", "normalized": "Y"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "source": {"parent_ids": []},
                    "ext": {"packet_context": {"group_index": 1, "source_group_index": 1, "source_type": "current", "origin_frame_id": "f1", "sequence_index": 1}},
                },
            ],
            "csa_items": [],
            "echo_frames": [],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "echo", "origin_frame_id": "f0", "sa_ids": ["sa_echo_0"], "csa_ids": [], "source_group_index": 0},
                {"group_index": 1, "source_type": "current", "origin_frame_id": "f1", "sa_ids": ["sa_current_0"], "csa_ids": [], "source_group_index": 1},
            ],
            "energy_summary": {"total_er": 1.5, "total_ev": 0.0},
        }
        internal_packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_001",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["A"]},
                        {"group_index": 1, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["B"]},
                    ],
                    "flat_tokens": ["A", "B"],
                    "er_hint": 1.0,
                    "ev_hint": 0.2,
                }
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )

        merged = engine.merge_stimulus_packets(external_packet, internal_packet, trace_id="merge_trace", tick_id="merge_tick")

        self.assertEqual(len(merged["grouped_sa_sequences"]), 2)
        self.assertEqual(merged["grouped_sa_sequences"][0]["sa_ids"], ["sa_echo_0"])
        self.assertEqual(merged["grouped_sa_sequences"][0]["csa_ids"], [])

        self.assertEqual(merged["grouped_sa_sequences"][1]["source_type"], "current")
        self.assertIn("sa_current_0", merged["grouped_sa_sequences"][1]["sa_ids"])
        self.assertTrue(merged["grouped_sa_sequences"][1]["ext"]["contains_internal_group"])
        self.assertEqual(merged["grouped_sa_sequences"][1]["ext"]["internal_merge_mode"], "append_to_last_external_group")

        profile = engine.build_sequence_profile_from_stimulus_packet(merged)
        self.assertEqual(len(profile["sequence_groups"]), 2)
        self.assertCountEqual(profile["sequence_groups"][1]["tokens"], ["Y", "A", "B"])

        units_by_id = {
            unit["unit_id"]: unit
            for unit in profile["sequence_groups"][1]["units"]
        }
        self.assertEqual(units_by_id["sa_current_0"]["source_type"], "current")

    def test_merge_internal_string_metadata_stays_inside_last_cooccurrence_group(self):
        engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})
        external_packet = {
            "id": "spkt_external_string",
            "object_type": "stimulus_packet",
            "current_frame_id": "spkt_external_string",
            "sa_items": [
                {
                    "id": "sa_current_0",
                    "object_type": "sa",
                    "content": {"raw": "Y", "display": "Y", "normalized": "Y"},
                    "stimulus": {"role": "feature", "modality": "text"},
                    "energy": {"er": 1.0, "ev": 0.0},
                    "source": {"parent_ids": []},
                    "ext": {
                        "packet_context": {
                            "group_index": 0,
                            "source_group_index": 0,
                            "source_type": "current",
                            "origin_frame_id": "f1",
                            "sequence_index": 0,
                        }
                    },
                },
            ],
            "csa_items": [],
            "grouped_sa_sequences": [
                {"group_index": 0, "source_type": "current", "origin_frame_id": "f1", "sa_ids": ["sa_current_0"], "csa_ids": [], "source_group_index": 0},
            ],
            "energy_summary": {"total_er": 1.0, "total_ev": 0.0},
        }
        internal_packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_string",
                    "sequence_groups": [
                        {
                            "group_index": 0,
                            "source_type": "internal",
                            "origin_frame_id": "frag_string",
                            "tokens": ["A", "B"],
                            "order_sensitive": True,
                            "string_unit_kind": "char_sequence",
                            "string_token_text": "AB",
                        },
                    ],
                    "flat_tokens": ["A", "B"],
                    "er_hint": 0.0,
                    "ev_hint": 0.8,
                }
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )

        merged = engine.merge_stimulus_packets(external_packet, internal_packet, trace_id="merge_trace", tick_id="merge_tick")

        self.assertEqual(len(merged["grouped_sa_sequences"]), 1)
        group = merged["grouped_sa_sequences"][0]
        self.assertEqual(group["source_type"], "current")
        self.assertTrue(group["ext"]["contains_internal_group"])
        self.assertEqual(group["ext"]["internal_merge_mode"], "append_to_last_external_group")
        self.assertEqual(group["ext"]["internal_string_groups"][0]["string_token_text"], "AB")

        profile = engine.build_sequence_profile_from_stimulus_packet(merged)
        self.assertEqual(len(profile["sequence_groups"]), 1)
        profile_group = profile["sequence_groups"][0]
        self.assertTrue(profile_group["order_sensitive"])
        self.assertEqual(profile_group["string_unit_kind"], "")
        self.assertEqual(profile_group["ext"]["internal_string_groups"][0]["string_token_text"], "AB")
        self.assertEqual(profile_group["tokens"], ["Y", "A", "B"])

    def test_merge_stimulus_packets_internal_only_still_returns_single_grouped_merged_packet(self):
        engine = CutEngine()
        internal_packet = engine.build_internal_stimulus_packet(
            [
                {
                    "fragment_id": "frag_001",
                    "sequence_groups": [
                        {"group_index": 0, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["A"]},
                        {"group_index": 1, "source_type": "internal", "origin_frame_id": "frag_001", "tokens": ["B"]},
                    ],
                    "flat_tokens": ["A", "B"],
                    "er_hint": 1.0,
                    "ev_hint": 0.2,
                }
            ],
            trace_id="cut_trace",
            tick_id="cut_tick",
        )

        merged = engine.merge_stimulus_packets(None, internal_packet, trace_id="merge_trace", tick_id="merge_tick")

        self.assertEqual(merged["packet_type"], "merged")
        self.assertEqual(len(merged["grouped_sa_sequences"]), 1)
        group = merged["grouped_sa_sequences"][0]
        self.assertEqual(group["source_type"], "internal")
        self.assertTrue(group["ext"]["contains_internal_group"])
        self.assertEqual(group["ext"]["internal_merge_mode"], "internal_only_packet")

    def test_sequence_signature_is_group_order_sensitive_but_group_internal_order_relaxed(self):
        engine = CutEngine()
        left = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f1", "tokens": ["B", "A"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f1", "tokens": ["C"]},
        ]
        same_groups_different_token_order = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f1", "tokens": ["A", "B"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f1", "tokens": ["C"]},
        ]
        reversed_group_order = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f1", "tokens": ["C"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f1", "tokens": ["A", "B"]},
        ]
        self.assertEqual(engine.sequence_groups_to_signature(left), engine.sequence_groups_to_signature(same_groups_different_token_order))
        self.assertNotEqual(engine.sequence_groups_to_signature(left), engine.sequence_groups_to_signature(reversed_group_order))

    def test_maximum_common_part_does_not_treat_reversed_group_order_as_full_match(self):
        engine = CutEngine()
        existing = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f1", "tokens": ["A", "B"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f1", "tokens": ["C"]},
        ]
        incoming = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f2", "tokens": ["C"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f2", "tokens": ["A", "B"]},
        ]
        result = engine.maximum_common_part(existing, incoming)
        self.assertLess(result["common_length"], 3)
        self.assertNotEqual(result["common_signature"], engine.sequence_groups_to_signature(existing))

    def test_maximum_common_part_exact_fast_path_preserves_full_match_semantics(self):
        engine = CutEngine({"maximum_common_part_exact_fast_path_enabled": True})
        existing = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f1", "tokens": ["A", "B"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f1", "tokens": ["C"]},
        ]
        incoming = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f2", "tokens": ["B", "A"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f2", "tokens": ["C"]},
        ]

        result = engine.maximum_common_part(existing, incoming)
        metrics = engine.pop_runtime_metrics()

        self.assertEqual(result["common_length"], 3)
        self.assertEqual(result["common_signature"], engine.sequence_groups_to_signature(existing))
        self.assertEqual(result["residual_existing_signature"], "")
        self.assertEqual(result["residual_incoming_signature"], "")
        self.assertEqual(metrics["maximum_common_part_exact_fast_path_hit_count"], 1)

    def test_maximum_common_part_full_inclusion_fast_path_preserves_residual_semantics(self):
        engine = CutEngine({"maximum_common_part_full_inclusion_fast_path_enabled": True})
        existing = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f1", "tokens": ["A", "B"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f1", "tokens": ["C"]},
        ]
        incoming = [
            {"group_index": 0, "source_type": "text", "origin_frame_id": "f2", "tokens": ["B", "A"]},
            {"group_index": 1, "source_type": "text", "origin_frame_id": "f2", "tokens": ["X"]},
            {"group_index": 2, "source_type": "text", "origin_frame_id": "f2", "tokens": ["C"]},
        ]

        result = engine.maximum_common_part(existing, incoming)
        metrics = engine.pop_runtime_metrics()

        self.assertEqual(result["common_length"], 3)
        self.assertEqual(result["matched_existing_group_indices"], [0, 1])
        self.assertEqual(result["matched_incoming_group_indices"], [0, 2])
        self.assertEqual(result["residual_existing_signature"], "")
        self.assertEqual(result["residual_incoming_tokens"], ["X"])
        self.assertEqual(metrics["maximum_common_part_full_inclusion_fast_path_hit_count"], 1)

    def test_csa_partial_overlap_keeps_bundle_only_when_anchor_and_attr_survive(self):
        engine = CutEngine()
        existing = [self._csa_group("A", ["x", "y"])]
        incoming = [self._csa_group("A", ["x"])]
        result = engine.maximum_common_part(existing, incoming)

        self.assertEqual(result["common_length"], 2)
        self.assertEqual(len(result["common_groups"]), 1)
        self.assertEqual(len(result["common_groups"][0]["csa_bundles"]), 1)
        self.assertEqual(result["common_groups"][0]["tokens"], ["A"])

        residual_existing = result["residual_existing_groups"][0]
        residual_tokens = [unit["token"] for unit in residual_existing["units"]]
        self.assertEqual(residual_tokens, ["y"])
        self.assertEqual(len(residual_existing["csa_bundles"]), 0)

    def test_csa_anchor_only_overlap_degrades_to_plain_sa(self):
        engine = CutEngine()
        existing = [self._csa_group("A", ["x"])]
        incoming = [
            {
                "group_index": 0,
                "source_type": "text",
                "origin_frame_id": "frame_0",
                "tokens": ["A"],
            }
        ]
        result = engine.maximum_common_part(existing, incoming)

        self.assertEqual(result["common_length"], 1)
        self.assertEqual(result["common_tokens"], ["A"])
        self.assertEqual(len(result["common_groups"][0]["csa_bundles"]), 0)
        self.assertEqual(result["residual_existing_groups"][0]["tokens"], ["x"])
        self.assertEqual(len(result["residual_existing_groups"][0]["csa_bundles"]), 0)

    def test_numeric_attribute_units_can_match_approximately_within_same_group(self):
        engine = CutEngine()
        engine.set_pointer_index(PointerIndex({}))
        existing = [
            {
                "group_index": 0,
                "source_type": "text",
                "origin_frame_id": "f1",
                "units": [
                    {
                        "unit_id": "feature_existing",
                        "token": "A",
                        "unit_role": "feature",
                        "sequence_index": 0,
                        "group_index": 0,
                        "source_group_index": 0,
                        "source_type": "text",
                        "origin_frame_id": "f1",
                        "display_visible": True,
                    },
                    {
                        "unit_id": "attr_existing",
                        "token": "stimulus_intensity:1.0",
                        "unit_role": "attribute",
                        "attribute_name": "stimulus_intensity",
                        "attribute_value": 1.0,
                        "sequence_index": 1,
                        "group_index": 0,
                        "source_group_index": 0,
                        "source_type": "text",
                        "origin_frame_id": "f1",
                        "display_visible": False,
                        "bundle_anchor_unit_id": "feature_existing",
                    },
                ],
                "csa_bundles": [
                    {
                        "bundle_id": "bundle_existing",
                        "anchor_unit_id": "feature_existing",
                        "member_unit_ids": ["feature_existing", "attr_existing"],
                    }
                ],
            }
        ]
        incoming = [
            {
                "group_index": 0,
                "source_type": "text",
                "origin_frame_id": "f2",
                "units": [
                    {
                        "unit_id": "feature_incoming",
                        "token": "A",
                        "unit_role": "feature",
                        "sequence_index": 0,
                        "group_index": 0,
                        "source_group_index": 0,
                        "source_type": "text",
                        "origin_frame_id": "f2",
                        "display_visible": True,
                    },
                    {
                        "unit_id": "attr_incoming",
                        "token": "stimulus_intensity:1.1",
                        "unit_role": "attribute",
                        "attribute_name": "stimulus_intensity",
                        "attribute_value": 1.1,
                        "sequence_index": 1,
                        "group_index": 0,
                        "source_group_index": 0,
                        "source_type": "text",
                        "origin_frame_id": "f2",
                        "display_visible": False,
                        "bundle_anchor_unit_id": "feature_incoming",
                    },
                ],
                "csa_bundles": [
                    {
                        "bundle_id": "bundle_incoming",
                        "anchor_unit_id": "feature_incoming",
                        "member_unit_ids": ["feature_incoming", "attr_incoming"],
                    }
                ],
            }
        ]

        result = engine.maximum_common_part(existing, incoming)

        self.assertEqual(result["common_length"], 2)
        self.assertEqual(result["matched_existing_unit_count"], 2)
        self.assertEqual(result["matched_incoming_unit_count"], 2)
        self.assertEqual(result["residual_existing_signature"], "")
        self.assertEqual(result["residual_incoming_signature"], "")
        self.assertNotEqual(result["common_signature"], engine.sequence_groups_to_signature(existing))
        common_units = result["common_groups"][0]["units"]
        self.assertTrue(any(str(unit.get("unit_signature", "")).startswith("AN:stimulus_intensity:") for unit in common_units))

    def test_numeric_attribute_unit_match_respects_similarity_threshold_config(self):
        engine = CutEngine(
            {
                "numeric_match_abs_tolerance": 0.01,
                "numeric_match_rel_tolerance": 0.01,
                "numeric_match_min_similarity": 0.4,
            }
        )
        numeric_match = engine._numeric_unit_match(
            existing_unit={
                "unit_role": "attribute",
                "attribute_name": "stimulus_intensity",
                "attribute_value": 1.0,
            },
            incoming_unit={
                "unit_role": "attribute",
                "attribute_name": "stimulus_intensity",
                "attribute_value": 1.05,
            },
        )
        self.assertIsNone(numeric_match)

    def test_pointer_index_numeric_match_allows_zero_nearby_match_with_abs_tolerance(self):
        pointer_index = PointerIndex({})
        numeric_match = pointer_index.describe_numeric_match(
            attribute_name="pressure",
            left_value=0.0,
            right_value=0.05,
        )
        self.assertIsNotNone(numeric_match)
        self.assertGreater(float(numeric_match.get("similarity", 0.0)), 0.4)
        self.assertAlmostEqual(float(numeric_match.get("tolerance", 0.0)), 0.2, places=6)

    def test_pointer_index_numeric_match_rejects_cross_zero_values(self):
        pointer_index = PointerIndex({})
        numeric_match = pointer_index.describe_numeric_match(
            attribute_name="pressure",
            left_value=-0.05,
            right_value=0.05,
        )
        self.assertIsNone(numeric_match)

    def test_structure_unit_match_uses_same_numeric_similarity_logic(self):
        engine = CutEngine()
        structure_match = engine._structure_unit_match(
            existing_unit={
                "object_type": "st",
                "structure_fuzzy_signature": "CSA[温度=>AN:temperature:NUM]",
                "structure_numeric_slots": [{"family": "temperature", "value": 1.0}],
                "structure_display_template": "温度{{NUM0}}",
                "display_text": "温度1.0",
            },
            incoming_unit={
                "object_type": "st",
                "structure_fuzzy_signature": "CSA[温度=>AN:temperature:NUM]",
                "structure_numeric_slots": [{"family": "temperature", "value": 1.1}],
                "structure_display_template": "温度{{NUM0}}",
                "display_text": "温度1.1",
            },
        )
        self.assertIsNotNone(structure_match)
        self.assertGreater(float(structure_match.get("similarity", 0.0)), 0.4)
        self.assertEqual(structure_match.get("average_numeric_slots"), [{"family": "temperature", "value": 1.05}])
        self.assertEqual(structure_match.get("common_display_text"), "温度1.05")

    def test_structure_unit_match_preserves_time_like_semantic_kind(self):
        engine = CutEngine()
        structure_match = engine._structure_unit_match(
            existing_unit={
                "object_type": "st",
                "structure_fuzzy_signature": "CSA[时间=>AN:时间感受:NUM]",
                "structure_numeric_slots": [{"family": "时间感受", "value": 2.0, "semantic_kind": "time_like"}],
                "structure_display_template": "间隔{{NUM0}}",
                "display_text": "间隔2.0",
            },
            incoming_unit={
                "object_type": "st",
                "structure_fuzzy_signature": "CSA[时间=>AN:时间感受:NUM]",
                "structure_numeric_slots": [{"family": "时间感受", "value": 2.2, "semantic_kind": "time_like"}],
                "structure_display_template": "间隔{{NUM0}}",
                "display_text": "间隔2.2",
            },
        )
        self.assertIsNotNone(structure_match)
        self.assertEqual(
            structure_match.get("average_numeric_slots"),
            [{"family": "时间感受", "value": 2.1, "semantic_kind": "time_like"}],
        )
        common_unit = engine._generalize_structure_common_unit(
            existing_unit={
                "object_type": "st",
                "structure_fuzzy_signature": "CSA[时间=>AN:时间感受:NUM]",
                "structure_display_template": "间隔{{NUM0}}",
                "structure_numeric_slots": [{"family": "时间感受", "value": 2.0, "semantic_kind": "time_like"}],
                "display_text": "间隔2.0",
                "unit_signature": "ST:time_a",
                "token": "time_a",
            },
            incoming_unit={
                "object_type": "st",
                "structure_fuzzy_signature": "CSA[时间=>AN:时间感受:NUM]",
                "structure_display_template": "间隔{{NUM0}}",
                "structure_numeric_slots": [{"family": "时间感受", "value": 2.2, "semantic_kind": "time_like"}],
                "display_text": "间隔2.2",
                "unit_signature": "ST:time_b",
                "token": "time_b",
            },
            structure_match=structure_match,
        )
        self.assertEqual(
            common_unit.get("structure_numeric_slots"),
            [{"family": "时间感受", "value": 2.1, "semantic_kind": "time_like"}],
        )

    def test_build_sequence_profile_preserves_structure_numeric_metadata(self):
        engine = CutEngine()
        group = {
            "group_index": 0,
            "source_type": "cam",
            "origin_frame_id": "frame_time",
            "units": [
                {
                    "unit_id": "st_time_1",
                    "object_type": "st",
                    "token": "st_time_1",
                    "display_text": "{计划}",
                    "unit_role": "feature",
                    "unit_signature": "ST:st_time_1",
                    "sequence_index": 0,
                    "display_visible": True,
                    "structure_display_text": "{计划}",
                    "structure_grouped_display_text": "{计划}",
                    "structure_display_template": "{计划}+{{NUM0}}",
                    "structure_fuzzy_signature": "U[F:计划]",
                    "structure_numeric_slots": [
                        {"family": "时间感受", "value": 2.0, "semantic_kind": "time_like"}
                    ],
                }
            ],
        }

        profile = engine.build_sequence_profile_from_groups([group])
        unit = profile["sequence_groups"][0]["units"][0]

        self.assertEqual(unit.get("structure_fuzzy_signature"), "U[F:计划]")
        self.assertEqual(unit.get("structure_display_template"), "{计划}+{{NUM0}}")
        self.assertEqual(
            unit.get("structure_numeric_slots"),
            [{"family": "时间感受", "value": 2.0, "semantic_kind": "time_like"}],
        )

    def _goal_b_string_group(self, text: str, *, group_index: int = 0) -> dict:
        return {
            "group_index": group_index,
            "source_type": "current",
            "origin_frame_id": f"goal_b_{group_index}",
            "order_sensitive": True,
            "string_unit_kind": "char_sequence",
            "string_token_text": text,
            "units": [
                {
                    "unit_id": f"goal_b_{group_index}_{index}_{char}",
                    "token": char,
                    "unit_role": "feature",
                    "sequence_index": index,
                    "group_index": group_index,
                    "source_group_index": group_index,
                    "source_type": "current",
                    "origin_frame_id": f"goal_b_{group_index}",
                    "display_visible": True,
                }
                for index, char in enumerate(text)
            ],
        }

    def test_goal_b_order_sensitive_signature_preserves_char_order(self):
        engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})

        forward = engine.sequence_groups_to_signature([self._goal_b_string_group("AB")])
        reversed_ = engine.sequence_groups_to_signature([self._goal_b_string_group("BA")])

        self.assertNotEqual(forward, reversed_)
        self.assertTrue(forward.startswith("OS["))

    def test_goal_b_order_sensitive_common_part_does_not_treat_reversed_string_as_full_match(self):
        engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})

        result = engine.maximum_common_part(
            [self._goal_b_string_group("AB")],
            [self._goal_b_string_group("BA")],
        )

        self.assertEqual(result["common_length"], 1)
        self.assertNotEqual(result["residual_existing_signature"], "")
        self.assertNotEqual(result["residual_incoming_signature"], "")

    def test_goal_b_order_sensitive_common_part_matches_prefix_and_keeps_residual(self):
        engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})

        result = engine.maximum_common_part(
            [self._goal_b_string_group("AB")],
            [self._goal_b_string_group("ABC")],
        )

        self.assertEqual(result["common_tokens"], ["A", "B"])
        self.assertEqual(result["residual_incoming_tokens"], ["C"])
        self.assertEqual(result["residual_existing_signature"], "")
        self.assertTrue(result["common_groups"][0].get("order_sensitive"))

    def test_single_group_fast_path_preserves_goal_b_prefix_residual(self):
        engine = CutEngine(
            {
                "enable_goal_b_char_sa_string_mode": True,
                "maximum_common_part_exact_fast_path_enabled": False,
                "maximum_common_part_full_inclusion_fast_path_enabled": False,
                "maximum_common_part_single_group_fast_path_enabled": True,
                "maximum_common_group_ordered_subsequence_fast_path_enabled": True,
            }
        )

        result = engine.maximum_common_part(
            [self._goal_b_string_group("AB")],
            [self._goal_b_string_group("ABC")],
        )
        metrics = engine.pop_runtime_metrics()

        self.assertEqual(result["common_tokens"], ["A", "B"])
        self.assertEqual(result["common_length"], 2)
        self.assertEqual(result["residual_existing_signature"], "")
        self.assertEqual(result["residual_incoming_tokens"], ["C"])
        self.assertTrue(result["common_groups"][0].get("order_sensitive"))
        self.assertEqual(metrics["maximum_common_part_single_group_fast_path_hit_count"], 1)
        self.assertGreaterEqual(metrics["maximum_common_group_ordered_subsequence_fast_path_hit_count"], 1)

    def test_single_group_fast_path_does_not_treat_reversed_goal_b_as_full_match(self):
        engine = CutEngine(
            {
                "enable_goal_b_char_sa_string_mode": True,
                "maximum_common_part_exact_fast_path_enabled": False,
                "maximum_common_part_full_inclusion_fast_path_enabled": False,
                "maximum_common_part_single_group_fast_path_enabled": True,
                "maximum_common_group_ordered_subsequence_fast_path_enabled": True,
            }
        )

        result = engine.maximum_common_part(
            [self._goal_b_string_group("AB")],
            [self._goal_b_string_group("BA")],
        )
        metrics = engine.pop_runtime_metrics()

        self.assertEqual(result["common_length"], 1)
        self.assertNotEqual(result["residual_existing_signature"], "")
        self.assertNotEqual(result["residual_incoming_signature"], "")
        self.assertEqual(metrics["maximum_common_part_single_group_fast_path_hit_count"], 1)

    def test_ordered_subsequence_fast_path_falls_back_on_repeated_signature_ambiguity(self):
        expected_engine = CutEngine(
            {
                "enable_goal_b_char_sa_string_mode": True,
                "maximum_common_part_exact_fast_path_enabled": False,
                "maximum_common_part_full_inclusion_fast_path_enabled": False,
                "maximum_common_part_single_group_fast_path_enabled": False,
                "maximum_common_group_ordered_subsequence_fast_path_enabled": False,
            }
        )
        fast_engine = CutEngine(
            {
                "enable_goal_b_char_sa_string_mode": True,
                "maximum_common_part_exact_fast_path_enabled": False,
                "maximum_common_part_full_inclusion_fast_path_enabled": False,
                "maximum_common_part_single_group_fast_path_enabled": True,
                "maximum_common_group_ordered_subsequence_fast_path_enabled": True,
            }
        )
        existing = [self._goal_b_string_group("ABA")]
        incoming = [self._goal_b_string_group("AA")]

        expected = expected_engine.maximum_common_part(existing, incoming)
        actual = fast_engine.maximum_common_part(existing, incoming)
        metrics = fast_engine.pop_runtime_metrics()

        self.assertEqual(actual["common_signature"], expected["common_signature"])
        self.assertEqual(actual["residual_existing_signature"], expected["residual_existing_signature"])
        self.assertEqual(actual["residual_incoming_signature"], expected["residual_incoming_signature"])
        self.assertEqual(metrics["maximum_common_part_single_group_fast_path_hit_count"], 1)
        self.assertNotIn("maximum_common_group_ordered_subsequence_fast_path_hit_count", metrics)


if __name__ == '__main__':
    unittest.main()



def test_goal_b_order_sensitive_string_display_omits_internal_plus():
    engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})
    group = {
        "group_index": 0,
        "source_type": "current",
        "origin_frame_id": "frame_a",
        "source_group_index": 0,
        "order_sensitive": True,
        "string_unit_kind": "char_sequence",
        "string_token_text": "ABC",
        "tokens": ["A", "B", "C"],
    }

    profile = engine.build_sequence_profile_from_groups([group])

    assert profile["display_text"] == "{ABC}"
    assert "+" not in profile["display_text"]


def test_goal_b_mixed_cooccurrence_display_joins_string_units_not_chars():
    engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})
    group = {
        "group_index": 0,
        "source_type": "merged",
        "origin_frame_id": "mix",
        "source_group_index": 0,
        "units": [
            {
                "unit_id": "u_a",
                "token": "A",
                "sequence_index": 0,
                "source_type": "current",
                "origin_frame_id": "frame_current",
                "source_group_index": 0,
                "order_sensitive": True,
                "string_unit_kind": "char_sequence",
                "string_token_text": "AB",
                "display_visible": True,
            },
            {
                "unit_id": "u_b",
                "token": "B",
                "sequence_index": 1,
                "source_type": "current",
                "origin_frame_id": "frame_current",
                "source_group_index": 0,
                "order_sensitive": True,
                "string_unit_kind": "char_sequence",
                "string_token_text": "AB",
                "display_visible": True,
            },
            {
                "unit_id": "u_c",
                "token": "C",
                "sequence_index": 2,
                "source_type": "internal",
                "origin_frame_id": "st_c",
                "source_group_index": 0,
                "display_visible": True,
            },
            {
                "unit_id": "u_d1",
                "token": "D",
                "sequence_index": 3,
                "source_type": "internal",
                "origin_frame_id": "st_d",
                "source_group_index": 0,
                "order_sensitive": True,
                "string_unit_kind": "char_sequence",
                "string_token_text": "DE",
                "display_visible": True,
            },
            {
                "unit_id": "u_d2",
                "token": "E",
                "sequence_index": 4,
                "source_type": "internal",
                "origin_frame_id": "st_d",
                "source_group_index": 0,
                "order_sensitive": True,
                "string_unit_kind": "char_sequence",
                "string_token_text": "DE",
                "display_visible": True,
            },
        ],
    }

    profile = engine.build_sequence_profile_from_groups([group])

    assert profile["display_text"] == "{AB + C + DE}"
    assert "A + B" not in profile["display_text"]
    assert "D + E" not in profile["display_text"]


def test_prebuilt_normalized_groups_roundtrip_profile_stays_stable():
    engine = CutEngine({"enable_goal_b_char_sa_string_mode": True})
    raw_group = {
        "group_index": 0,
        "source_type": "current",
        "origin_frame_id": "stable_roundtrip",
        "order_sensitive": True,
        "string_unit_kind": "char_sequence",
        "string_token_text": "ABC",
        "units": [
            {
                "unit_id": f"stable_{index}_{char}",
                "token": char,
                "unit_role": "feature",
                "sequence_index": index,
                "group_index": 0,
                "source_group_index": 0,
                "source_type": "current",
                "origin_frame_id": "stable_roundtrip",
                "display_visible": True,
                "order_sensitive": True,
                "string_unit_kind": "char_sequence",
                "string_token_text": "ABC",
            }
            for index, char in enumerate("ABC")
        ],
    }

    first = engine.build_sequence_profile_from_groups([raw_group])
    second = engine.build_sequence_profile_from_groups(first["sequence_groups"])

    assert second["content_signature"] == first["content_signature"]
    assert second["display_text"] == first["display_text"]
    assert second["flat_tokens"] == first["flat_tokens"]
    assert second["flat_unit_signatures"] == first["flat_unit_signatures"]
    assert len(second["all_units"]) == 3
    assert second["all_unit_token_counts"] == {"A": 1, "B": 1, "C": 1}
