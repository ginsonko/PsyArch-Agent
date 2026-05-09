# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


def _make_fragment(structure_id: str, unit_count: int) -> dict:
    # Minimal internal fragment shape consumed by CutEngine.build_internal_stimulus_packet.
    units = []
    for i in range(int(unit_count)):
        token = f"t{i}"
        units.append(
            {
                "unit_id": f"{structure_id}_u{i}",
                "unit_signature": f"F:{token}",
                "unit_role": "feature",
                "token": token,
                "display_text": token,
                "display_visible": True,
                "sequence_index": int(i),
                # Provide energy hints to avoid division by zero in scoring.
                "er": 1.0,
                "ev": 0.0,
                "total_energy": 1.0,
                # Bundle fields (kept empty for this test)
                "bundle_id": "",
                "bundle_anchor_unit_id": "",
                "bundle_signature": "",
                "bundle_member_unit_ids": [],
            }
        )

    return {
        "fragment_id": f"sif_{structure_id}",
        "source_group_id": "",
        "source_phase": "test",
        "source_structure_id": structure_id,
        "display_text": f"{{{structure_id}}}",
        "flat_tokens": [u["token"] for u in units],
        "sequence_groups": [
            {
                "group_index": 0,
                "source_type": "internal",
                "origin_frame_id": structure_id,
                "units": units,
                "tokens": [u["token"] for u in units],
                "csa_bundles": [],
            }
        ],
        "er_hint": 1.0,
        "ev_hint": 0.0,
        "energy_hint": 1.0,
    }


def _make_fragment_tokens_only(structure_id: str, token_count: int) -> dict:
    tokens = [f"t{i}" for i in range(int(token_count))]
    return {
        "fragment_id": f"sif_{structure_id}",
        "source_group_id": "",
        "source_phase": "test",
        "source_structure_id": structure_id,
        "display_text": f"{{{structure_id}}}",
        "flat_tokens": list(tokens),
        "sequence_groups": [
            {
                "group_index": 0,
                "source_type": "internal",
                "origin_frame_id": structure_id,
                "tokens": list(tokens),
                # Intentionally no `units` here: this is the legacy shape.
            }
        ],
        "er_hint": 1.0,
        "ev_hint": 0.0,
        "energy_hint": 1.0,
    }


class TestInternalResidualResolution(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="hdb_internal_resolution_")
        self.hdb = HDB(
            config_override={
                "data_dir": self.temp_dir,
                "enable_background_repair": False,
                # Make the test deterministic and fast.
                "internal_resolution_enabled": True,
                "internal_resolution_detail_budget_base": 50,
                "internal_resolution_detail_budget_adr_gain": 0,
                "internal_resolution_min_detail_per_structure": 4,
                "internal_resolution_max_detail_per_structure": 20,
                "internal_resolution_stable_anchor_count": 1,
                "internal_resolution_anchor_ratio": 0.3,
                "internal_resolution_detail_fatigue_window": 32,
                "internal_resolution_detail_fatigue_start": 1.0,
                "internal_resolution_detail_fatigue_full": 4.0,
                "internal_resolution_detail_fatigue_min_scale": 0.0,
                "internal_resolution_focus_credit_enabled": True,
                "internal_resolution_focus_credit_gain": 0.5,
                "internal_resolution_focus_credit_decay": 0.9,
                "internal_resolution_focus_credit_cap": 2.0,
                "internal_resolution_focus_credit_gamma": 0.25,
                "internal_resolution_rich_structure_ratio": 0.4,
                "internal_resolution_rich_structure_min_units": 6,
                "internal_resolution_structure_richness_power": 0.5,
                "internal_storage_projection_enabled": True,
                "internal_storage_projection_ratio": 0.25,
                "internal_storage_projection_max_fragments_per_round": 1,
                "internal_attention_landscape_enabled": True,
                "internal_attention_landscape_ratio": 0.2,
                # Runtime NT snapshot (ADR=0 -> budget==base)
                "_runtime_nt_snapshot": {"ADR": 0.0},
            }
        )

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_budget_caps_total_selected_units(self):
        engine = self.hdb._structure_retrieval
        fragments = [
            _make_fragment("st_a", 100),
            _make_fragment("st_b", 100),
            _make_fragment("st_c", 100),
        ]
        cam_items = [
            {"structure_id": "st_a", "cp_abs": 1.0, "runtime_weight": 1.0},
            {"structure_id": "st_b", "cp_abs": 0.5, "runtime_weight": 1.0},
            {"structure_id": "st_c", "cp_abs": 0.2, "runtime_weight": 1.0},
        ]
        trimmed, summary = engine._apply_internal_resolution_to_fragments(
            fragments=fragments,
            cam_items=cam_items,
            cam_structure_ids=["st_a", "st_b", "st_c"],
            now_ms=0,
            trace_id="t",
            tick_id="t",
        )
        self.assertTrue(summary.get("enabled", False))
        self.assertEqual(int(summary.get("detail_budget", 0)), 50)
        self.assertLessEqual(int(summary.get("selected_unit_count", 0)), 50)
        self.assertEqual(len(trimmed), 3)

    def test_progressive_cursor_changes_across_calls(self):
        engine = self.hdb._structure_retrieval
        fragment = _make_fragment("st_long", 120)
        f1, info1 = engine._trim_internal_fragment_units(fragment=fragment, target_unit_count=20, focus_credit=0.0)
        f2, info2 = engine._trim_internal_fragment_units(fragment=fragment, target_unit_count=20, focus_credit=0.0)
        self.assertEqual(int(info1.get("selected_unit_count", 0)), 20)
        self.assertEqual(int(info2.get("selected_unit_count", 0)), 20)
        self.assertNotEqual(int(info1.get("cursor_after", 0)), int(info2.get("cursor_after", 0)))
        # Ensure we really trimmed (not returning full fragment)
        self.assertLess(int(info1.get("selected_unit_count", 0)), int(info1.get("raw_unit_count", 0)))

    def test_token_only_fragments_are_trimmed(self):
        engine = self.hdb._structure_retrieval
        fragments = [
            _make_fragment_tokens_only("st_a", 100),
            _make_fragment_tokens_only("st_b", 100),
            _make_fragment_tokens_only("st_c", 100),
        ]
        cam_items = [
            {"structure_id": "st_a", "cp_abs": 1.0, "runtime_weight": 1.0},
            {"structure_id": "st_b", "cp_abs": 0.5, "runtime_weight": 1.0},
            {"structure_id": "st_c", "cp_abs": 0.2, "runtime_weight": 1.0},
        ]
        trimmed, summary = engine._apply_internal_resolution_to_fragments(
            fragments=fragments,
            cam_items=cam_items,
            cam_structure_ids=["st_a", "st_b", "st_c"],
            now_ms=0,
            trace_id="t",
            tick_id="t",
        )
        self.assertTrue(summary.get("enabled", False))
        self.assertEqual(int(summary.get("detail_budget", 0)), 50)
        self.assertGreater(int(summary.get("raw_unit_count", 0)), 0)
        self.assertGreater(int(summary.get("selected_unit_count", 0)), 0)
        self.assertLessEqual(int(summary.get("selected_unit_count", 0)), 50)

        # Ensure the trimmed fragments really result in a bounded internal SA packet.
        pkt = self.hdb._cut.build_internal_stimulus_packet(trimmed, trace_id="t", tick_id="t")
        self.assertLessEqual(len(pkt.get("sa_items", []) or []), 50)

    def test_hybrid_selection_preserves_rich_fragments(self):
        engine = self.hdb._structure_retrieval
        engine.update_config(
            {
                **engine._config,
                "internal_resolution_detail_budget_base": 80,
                "internal_resolution_min_detail_per_structure": 4,
                "internal_resolution_max_detail_per_structure": 32,
                "internal_resolution_max_structures_per_tick": 3,
                "internal_resolution_rich_structure_ratio": 0.4,
                "internal_resolution_rich_structure_min_units": 6,
                "internal_resolution_structure_richness_power": 0.5,
            }
        )
        fragments = [
            _make_fragment("st_big", 20),
            _make_fragment("st_s1", 1),
            _make_fragment("st_s2", 1),
            _make_fragment("st_s3", 1),
            _make_fragment("st_s4", 1),
            _make_fragment("st_s5", 1),
        ]
        cam_items = [
            {"structure_id": "st_big", "cp_abs": 0.4, "runtime_weight": 1.0},
            {"structure_id": "st_s1", "cp_abs": 0.4, "runtime_weight": 1.0},
            {"structure_id": "st_s2", "cp_abs": 0.4, "runtime_weight": 1.0},
            {"structure_id": "st_s3", "cp_abs": 0.4, "runtime_weight": 1.0},
            {"structure_id": "st_s4", "cp_abs": 0.4, "runtime_weight": 1.0},
            {"structure_id": "st_s5", "cp_abs": 0.4, "runtime_weight": 1.0},
        ]
        trimmed, summary = engine._apply_internal_resolution_to_fragments(
            fragments=fragments,
            cam_items=cam_items,
            cam_structure_ids=[item["structure_id"] for item in cam_items],
            now_ms=0,
            trace_id="t",
            tick_id="t",
        )
        self.assertEqual(int(summary.get("structure_count_selected", 0)), 3)
        self.assertGreaterEqual(int(summary.get("rich_candidate_count", 0)), 1)
        self.assertGreaterEqual(int(summary.get("rich_selected_count", 0)), 1)
        self.assertEqual(summary.get("selection_mode", ""), "hybrid_density_rich")
        kept_ids = {str(fragment.get("source_structure_id", "")) for fragment in trimmed}
        self.assertIn("st_big", kept_ids)
        self.assertEqual(int(summary.get("selected_unit_count", 0)), 22)
        big_fragment = next(fragment for fragment in trimmed if str(fragment.get("source_structure_id", "")) == "st_big")
        self.assertEqual(len(big_fragment.get("flat_tokens", []) or []), 20)

    def test_structure_id_count_cover_respects_multiplicity(self):
        engine = self.hdb._structure_retrieval
        required = engine._count_structure_ids(["st_a", "st_a", "st_b"])
        enough = engine._count_structure_ids(["st_a", "st_a", "st_b", "st_c"])
        not_enough = engine._count_structure_ids(["st_a", "st_b", "st_c"])
        self.assertTrue(engine._structure_id_counts_cover(required_counts=required, available_counts=enough))
        self.assertFalse(engine._structure_id_counts_cover(required_counts=required, available_counts=not_enough))

    def test_active_group_fragment_projects_group_landscape(self):
        cut = self.hdb._cut
        store = self.hdb._structure_store
        group_store = self.hdb._group_store
        engine = self.hdb._structure_retrieval

        created = []
        for token in ["提醒", "喝水", "回到日程"]:
            structure_obj, _ = store.create_structure(
                structure_payload=cut.make_structure_payload_from_tokens([token], confidence=0.9),
                trace_id="t",
                tick_id="t",
            )
            created.append(structure_obj)

        required_ids = [str(item.get("id", "")) for item in created if str(item.get("id", ""))]
        group_obj = group_store.create_group(
            required_structure_ids=required_ids,
            avg_energy_profile={sid: 1.0 for sid in required_ids},
            trace_id="t",
            tick_id="t",
        )

        fragment = engine._build_internal_group_fragment(
            group_obj=group_obj,
            required_ids=required_ids,
            matched_er_total=3.0,
            matched_ev_total=1.5,
            rho=0.5,
            structure_store=store,
            group_store=group_store,
            cut_engine=cut,
            profile_cache={},
        )

        self.assertIsNotNone(fragment)
        self.assertEqual(str(fragment.get("source_structure_id", "")), str(group_obj.get("id", "")))
        self.assertEqual(str(fragment.get("source_owner_kind", "")), "sg")
        self.assertGreaterEqual(len(fragment.get("flat_tokens", []) or []), 3)
        self.assertAlmostEqual(float(fragment.get("er_hint", 0.0) or 0.0), 1.5, places=6)
        self.assertAlmostEqual(float(fragment.get("ev_hint", 0.0) or 0.0), 0.75, places=6)

    def test_storage_residual_projection_uses_canonical_sequence_groups(self):
        engine = self.hdb._structure_retrieval
        fragment = _make_fragment("st_ctx", 4)
        storage_summary = {
            "owner_kind": "st",
            "owner_id": "st_anchor",
            "actions": [
                {
                    "type": "append_raw_residual",
                    "entry_id": "sgr_000001",
                    "canonical_display_text": "{提醒} / {回到日程}",
                    "canonical_signature": "sig_ctx",
                    "canonical_sequence_groups": list(fragment.get("sequence_groups", [])),
                }
            ],
        }

        projected = engine._build_internal_storage_fragments(
            storage_summary=storage_summary,
            source_group_id="sg_single_st_anchor",
            source_phase="storage_residual_round",
            fallback_total_er=1.0,
            fallback_total_ev=0.0,
            cut_engine=self.hdb._cut,
        )

        self.assertEqual(len(projected), 1)
        item = projected[0]
        self.assertEqual(str(item.get("source_phase", "")), "storage_residual_round")
        self.assertEqual(str(item.get("source_owner_kind", "")), "storage_residual")
        self.assertEqual(str(item.get("source_structure_id", "")), "sgr_000001")
        self.assertGreaterEqual(len(item.get("flat_tokens", []) or []), 4)
        self.assertGreater(float(item.get("er_hint", 0.0) or 0.0), 0.0)

    def test_attention_landscape_projection_aggregates_active_items(self):
        cut = self.hdb._cut
        store = self.hdb._structure_store
        engine = self.hdb._structure_retrieval

        structure_obj, _ = store.create_structure(
            structure_payload=cut.make_structure_payload_from_tokens(["提醒", "喝水", "回到日程"], confidence=0.9),
            trace_id="t",
            tick_id="t",
        )

        fragment = engine._build_attention_landscape_fragment(
            items=[
                {
                    "item_id": "item_st",
                    "ref_object_type": "st",
                    "ref_object_id": str(structure_obj.get("id", "")),
                    "display": "{提醒/喝水/回到日程}",
                    "er": 2.0,
                    "ev": 0.5,
                },
                {
                    "item_id": "item_sa",
                    "ref_object_type": "sa",
                    "ref_object_id": "sa_focus",
                    "display": "先喝一口水",
                    "er": 1.0,
                    "ev": 0.0,
                },
            ],
            tick_id="cycle_0001",
            structure_store=store,
            group_store=self.hdb._group_store,
            cut_engine=cut,
            total_er=3.0,
            total_ev=0.5,
            profile_cache={},
        )

        self.assertIsNotNone(fragment)
        self.assertEqual(str(fragment.get("source_phase", "")), "attention_landscape")
        self.assertEqual(str(fragment.get("source_owner_kind", "")), "attention_landscape")
        self.assertGreaterEqual(len(fragment.get("flat_tokens", []) or []), 4)
        self.assertGreater(float(fragment.get("er_hint", 0.0) or 0.0), 0.0)


if __name__ == "__main__":
    unittest.main()
