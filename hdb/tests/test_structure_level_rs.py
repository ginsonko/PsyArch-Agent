# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestHDBStructureLevelRS(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_structure_rs_')
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _packet(self, text: str) -> dict:
        sa_items = []
        for idx, ch in enumerate(text):
            sa_items.append({
                'id': f'sa_sg_{text}_{idx}',
                'object_type': 'sa',
                'content': {'raw': ch, 'display': ch, 'normalized': ch},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': idx}},
            })
        return {
            'id': f'spkt_sg_{text}',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_sg', 'sa_ids': [item['id'] for item in sa_items], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _grouped_numeric_packet(self, anchor_text: str, intensity: float, *, packet_id: str) -> dict:
        anchor_id = f'{packet_id}_sa_anchor'
        attr_id = f'{packet_id}_sa_attr'
        csa_id = f'{packet_id}_csa'
        return {
            'id': packet_id,
            'object_type': 'stimulus_packet',
            'sa_items': [
                {
                    'id': anchor_id,
                    'object_type': 'sa',
                    'content': {'raw': anchor_text, 'display': anchor_text, 'normalized': anchor_text},
                    'stimulus': {'role': 'feature', 'modality': 'text'},
                    'energy': {'er': float(intensity), 'ev': 0.0},
                    'ext': {'packet_context': {'group_index': 0, 'sequence_index': 0, 'source_type': 'current'}},
                },
                {
                    'id': attr_id,
                    'object_type': 'sa',
                    'content': {
                        'raw': f'stimulus_intensity:{intensity}',
                        'display': f'stimulus_intensity:{intensity}',
                        'normalized': f'stimulus_intensity:{intensity}',
                        'value_type': 'numerical',
                        'attribute_name': 'stimulus_intensity',
                        'attribute_value': float(intensity),
                    },
                    'stimulus': {'role': 'attribute', 'modality': 'text'},
                    'energy': {'er': float(intensity) * 0.25, 'ev': 0.0},
                    'source': {'parent_ids': [anchor_id]},
                    'ext': {'packet_context': {'group_index': 0, 'sequence_index': 1, 'source_type': 'current'}},
                },
            ],
            'csa_items': [
                {
                    'id': csa_id,
                    'object_type': 'csa',
                    'anchor_sa_id': anchor_id,
                    'member_sa_ids': [anchor_id, attr_id],
                    'content': {'display': f'CSA[{anchor_text}]', 'raw': anchor_text},
                    'energy': {'er': float(intensity) * 1.25, 'ev': 0.0},
                    'ext': {'packet_context': {'group_index': 0, 'sequence_index': 2}},
                }
            ],
            'grouped_sa_sequences': [
                {
                    'group_index': 0,
                    'source_type': 'current',
                    'origin_frame_id': f'frame_{packet_id}',
                    'sa_ids': [anchor_id],
                    'csa_ids': [csa_id],
                }
            ],
            'energy_summary': {'current_total_er': float(intensity) * 1.25, 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _seed_atomic(self, token: str, trace_id: str) -> str:
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet(token),
            trace_id=trace_id,
        )
        structure_ids = result['data'].get('seeded_atomic_structure_ids') or result['data'].get('new_structure_ids') or []
        self.assertEqual(len(structure_ids), 1)
        return structure_ids[0]

    def _find_structure_by_flat_tokens(self, expected_tokens: list[str]) -> dict | None:
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == list(expected_tokens):
                return structure_obj
        return None

    def _snapshot(self, entries: list[tuple[str, float, float]]) -> dict:
        return {
            'summary': {'active_item_count': len(entries)},
            'top_items': [
                {
                    'id': f'node_{index}',
                    'ref_object_type': 'st',
                    'ref_object_id': structure_id,
                    'display': structure_id,
                    'er': er,
                    'ev': ev,
                }
                for index, (structure_id, er, ev) in enumerate(entries, start=1)
            ],
        }

    def test_group_is_created_from_overlap_then_matched_via_owner_chain(self):
        structure_a = self._seed_atomic('A', 'sg_seed_a')
        structure_b = self._seed_atomic('B', 'sg_seed_b')
        structure_x = self._seed_atomic('X', 'sg_seed_x')
        structure_y = self._seed_atomic('Y', 'sg_seed_y')
        structure_z = self._seed_atomic('Z', 'sg_seed_z')

        first_snapshot = self._snapshot([
            (structure_a, 5.0, 0.2),
            (structure_b, 3.0, 0.2),
            (structure_x, 2.0, 0.2),
        ])
        first_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=first_snapshot,
            trace_id='sg_round_1',
            top_n=3,
        )
        self.assertTrue(first_result['success'])
        self.assertEqual(first_result['data']['new_group_ids'], [])
        self.assertEqual(first_result['data']['matched_group_ids'], [])
        owner_a_db = self.hdb._structure_store.get_db_by_owner(structure_a)
        self.assertIsNotNone(owner_a_db)
        self.assertEqual(len(owner_a_db.get('group_residual_table', [])), 1)
        self.assertEqual(owner_a_db.get('group_table', []), [])

        second_snapshot = self._snapshot([
            (structure_a, 5.0, 0.2),
            (structure_b, 3.0, 0.2),
            (structure_y, 2.0, 0.2),
        ])
        second_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=second_snapshot,
            trace_id='sg_round_2',
            top_n=3,
        )
        self.assertTrue(second_result['success'])
        self.assertEqual(len(second_result['data']['new_group_ids']), 1)
        group_id = second_result['data']['new_group_ids'][0]
        owner_a_db = self.hdb._structure_store.get_db_by_owner(structure_a)
        self.assertTrue(any(entry.get('group_id') == group_id for entry in owner_a_db.get('group_table', [])))
        group_obj = self.hdb._group_store.get(group_id)
        self.assertIsNotNone(group_obj)
        self.assertEqual(group_obj.get('required_structure_ids'), [structure_a, structure_b])
        self.assertEqual(len(group_obj.get('local_db', {}).get('residual_table', [])), 2)

        third_snapshot = self._snapshot([
            (structure_a, 5.0, 0.2),
            (structure_b, 3.0, 0.2),
            (structure_z, 2.0, 0.2),
        ])
        third_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=third_snapshot,
            trace_id='sg_round_3',
            top_n=3,
        )
        self.assertTrue(third_result['success'])
        self.assertIn(group_id, third_result['data']['matched_group_ids'])
        self.assertGreaterEqual(third_result['data']['round_count'], 1)
        selected_group = next(
            (detail.get('selected_group') for detail in third_result['data']['debug']['round_details'] if detail.get('selected_group')),
            None,
        )
        self.assertIsNotNone(selected_group)
        self.assertEqual(selected_group.get('group_id'), group_id)

    def test_invalid_overlap_without_owner_containment_does_not_create_common_group(self):
        structure_a = self._seed_atomic('A', 'sg_owner_a')
        structure_b = self._seed_atomic('B', 'sg_owner_b')
        structure_c = self._seed_atomic('C', 'sg_owner_c')

        first_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (structure_a, 5.0, 0.2),
                (structure_b, 4.0, 0.2),
            ]),
            trace_id='sg_invalid_overlap_1',
            top_n=2,
        )
        self.assertTrue(first_result['success'])
        owner_a_db = self.hdb._structure_store.get_db_by_owner(structure_a)
        self.assertIsNotNone(owner_a_db)
        self.assertEqual(len(owner_a_db.get('group_residual_table', [])), 1)
        self.assertEqual(owner_a_db.get('group_table', []), [])

        second_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (structure_b, 4.0, 0.2),
                (structure_a, 5.0, 0.2),
                (structure_c, 3.0, 0.2),
            ]),
            trace_id='sg_invalid_overlap_2',
            top_n=3,
        )
        self.assertTrue(second_result['success'])
        self.assertEqual(second_result['data']['new_group_ids'], [])

        owner_a_db = self.hdb._structure_store.get_db_by_owner(structure_a)
        self.assertIsNotNone(owner_a_db)
        self.assertEqual(owner_a_db.get('group_table', []), [])
        self.assertEqual(len(owner_a_db.get('group_residual_table', [])), 2)

    def test_numeric_anchor_group_match_surfaces_v2_numeric_score(self):
        seed_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._grouped_numeric_packet('A', 1.0, packet_id='sg_num_a'),
            trace_id='sg_num_seed_a',
        )
        self.assertTrue(seed_result['success'])

        structure_a = self._find_structure_by_flat_tokens(['A'])
        numeric_anchor = self._find_structure_by_flat_tokens(['stimulus_intensity:1.0'])
        self.assertIsNotNone(structure_a)
        self.assertIsNotNone(numeric_anchor)

        structure_x = self._seed_atomic('X', 'sg_num_x')
        structure_y = self._seed_atomic('Y', 'sg_num_y')
        structure_z = self._seed_atomic('Z', 'sg_num_z')

        first_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (numeric_anchor['id'], 6.0, 0.1),
                (structure_a['id'], 5.0, 0.1),
                (structure_x, 2.0, 0.1),
            ]),
            trace_id='sg_num_round_1',
            top_n=3,
        )
        self.assertTrue(first_result['success'])
        self.assertEqual(first_result['data']['new_group_ids'], [])

        second_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (numeric_anchor['id'], 6.0, 0.1),
                (structure_a['id'], 5.0, 0.1),
                (structure_y, 2.0, 0.1),
            ]),
            trace_id='sg_num_round_2',
            top_n=3,
        )
        self.assertTrue(second_result['success'])
        self.assertEqual(len(second_result['data']['new_group_ids']), 1)
        group_id = second_result['data']['new_group_ids'][0]

        third_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (numeric_anchor['id'], 6.0, 0.1),
                (structure_a['id'], 5.0, 0.1),
                (structure_z, 2.0, 0.1),
            ]),
            trace_id='sg_num_round_3',
            top_n=3,
        )
        self.assertTrue(third_result['success'])
        self.assertIn(group_id, third_result['data']['matched_group_ids'])

        round_details = third_result['data']['debug']['round_details']
        selected_group = next(
            (
                detail.get('selected_group')
                for detail in round_details
                if isinstance(detail.get('selected_group'), dict)
                and detail.get('selected_group', {}).get('group_id') == group_id
            ),
            None,
        )
        self.assertIsNotNone(selected_group)
        self.assertEqual(selected_group.get('group_kind'), 'group')
        self.assertIs(selected_group.get('synthetic'), False)
        self.assertGreater(float(selected_group.get('competition_score_v2', 0.0)), 0.0)
        self.assertGreater(float(selected_group.get('v2_numeric_score', -1.0)), 0.0)

        candidate_groups = [
            candidate
            for detail in round_details
            for candidate in detail.get('candidate_groups', [])
            if candidate.get('group_id') == group_id
        ]
        self.assertTrue(candidate_groups)
        self.assertTrue(any(float(candidate.get('competition_score_v2', 0.0)) > 0.0 for candidate in candidate_groups))
        self.assertTrue(any(float(candidate.get('v2_numeric_score', -1.0)) > 0.0 for candidate in candidate_groups))

    def test_common_group_reuse_uses_indexed_candidates_without_global_scan(self):
        structure_a = self._seed_atomic('A', 'sg_index_seed_a')
        structure_b = self._seed_atomic('B', 'sg_index_seed_b')
        structure_x = self._seed_atomic('X', 'sg_index_seed_x')
        structure_y = self._seed_atomic('Y', 'sg_index_seed_y')
        structure_z = self._seed_atomic('Z', 'sg_index_seed_z')

        first_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (structure_a, 5.0, 0.2),
                (structure_b, 3.0, 0.2),
                (structure_x, 2.0, 0.2),
            ]),
            trace_id='sg_index_round_1',
            top_n=3,
        )
        self.assertTrue(first_result['success'])
        second_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (structure_a, 5.0, 0.2),
                (structure_b, 3.0, 0.2),
                (structure_y, 2.0, 0.2),
            ]),
            trace_id='sg_index_round_2',
            top_n=3,
        )
        self.assertTrue(second_result['success'])
        self.assertEqual(len(second_result['data']['new_group_ids']), 1)
        group_id = second_result['data']['new_group_ids'][0]
        group_obj = self.hdb._group_store.get(group_id)
        self.assertIsNotNone(group_obj)
        signature = group_obj.get('group_structure', {}).get('content_signature', '')
        self.assertEqual(self.hdb._group_store.query_by_signature(signature)[0].get('id'), group_id)
        self.assertEqual(self.hdb._group_store.query_by_required_structures([structure_a, structure_b])[0].get('id'), group_id)

        def fail_iter_items():
            raise AssertionError('common group reuse should query GroupStore indexes instead of scanning all groups')

        self.hdb._group_store.iter_items = fail_iter_items
        third_result = self.hdb.run_structure_level_retrieval_storage(
            state_snapshot=self._snapshot([
                (structure_a, 5.0, 0.2),
                (structure_b, 3.0, 0.2),
                (structure_z, 2.0, 0.2),
            ]),
            trace_id='sg_index_round_3',
            top_n=3,
        )
        self.assertTrue(third_result['success'])
        self.assertIn(group_id, third_result['data']['matched_group_ids'])

    def test_runtime_profile_from_cam_preserves_time_like_runtime_numeric_slots(self):
        structure_a = self._seed_atomic('A', 'sg_time_seed_a')
        structure_obj = self.hdb._structure_store.get(structure_a)
        self.assertIsNotNone(structure_obj)

        profile = self.hdb._structure_retrieval._build_runtime_profile_from_cam(
            cam_items=[
                {
                    'structure_id': structure_a,
                    'structure_obj': structure_obj,
                    'runtime_bound_attribute_units': [
                        {
                            'attribute_name': '时间感受',
                            'attribute_value': 2.0,
                            'meta': {
                                'ext': {
                                    'time_bucket_id': 'tb_runtime',
                                    'time_bucket_center_sec': 2.0,
                                    'time_basis': 'tick',
                                    'delta_value': 2.0,
                                }
                            },
                        }
                    ],
                    'display_text': '{A}',
                    'er': 1.0,
                    'ev': 0.2,
                    'order_index': 0,
                }
            ],
            budget_er_map={structure_a: 1.0},
            budget_ev_map={structure_a: 0.2},
            cut_engine=self.hdb._cut,
            origin_frame_id='sg_time_tick',
            structure_store=self.hdb._structure_store,
        )

        units = [
            unit
            for group in profile.get('sequence_groups', [])
            for unit in group.get('units', [])
            if isinstance(unit, dict) and unit.get('unit_id') == structure_a
        ]
        self.assertEqual(len(units), 1)
        self.assertEqual(
            units[0].get('structure_numeric_slots'),
            [{'family': '时间感受', 'value': 2.0, 'semantic_kind': 'time_like'}],
        )

    def test_internal_fragment_from_profile_projects_runtime_numeric_attributes_into_internal_packet(self):
        structure_a = self._seed_atomic('A', 'sg_time_internal_attr_seed_a')
        structure_obj = self.hdb._structure_store.get(structure_a)
        self.assertIsNotNone(structure_obj)
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg['internal_fragment_include_runtime_bound_attributes'] = True
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        restored_profile = self.hdb._structure_retrieval._profile_from_stored_groups(
            list(structure_obj.get('structure', {}).get('sequence_groups', [])),
            cut_engine=self.hdb._cut,
            ext={'kind': 'test_internal_runtime_attr_projection'},
        )
        fragment = self.hdb._structure_retrieval._build_internal_fragment_from_profile(
            owner_id=structure_a,
            owner_kind='st',
            source_group_id='sg_runtime_attr_projection',
            source_phase='unit_test',
            display_text='{A}',
            profile=restored_profile,
            total_er=1.0,
            total_ev=0.2,
            runtime_bound_attribute_units=[
                {
                    'attribute_name': '时间感受',
                    'attribute_value': 2.0,
                    'meta': {
                        'ext': {
                            'time_bucket_id': 'tb_internal_projection',
                            'time_bucket_center_sec': 2.0,
                            'time_basis': 'tick',
                            'delta_value': 2.0,
                        }
                    },
                }
            ],
        )

        self.assertIsNotNone(fragment)
        packet = self.hdb._cut.build_internal_stimulus_packet(
            [fragment],
            trace_id='trace_internal_runtime_attr_projection',
            tick_id='cycle_internal_runtime_attr_projection',
        )
        attribute_items = [
            item
            for item in packet.get('sa_items', [])
            if (item.get('stimulus', {}) or {}).get('role') == 'attribute'
        ]
        self.assertEqual(len(attribute_items), 1)
        attr_content = attribute_items[0].get('content', {}) or {}
        self.assertEqual(attr_content.get('attribute_name'), '时间感受')
        self.assertEqual(attr_content.get('attribute_value'), 2.0)
        self.assertEqual(attr_content.get('value_type'), 'numerical')

    def test_internal_runtime_attribute_projection_prioritizes_configured_families_before_max_count_clip(self):
        structure_a = self._seed_atomic('A', 'sg_runtime_attr_priority_seed_a')
        structure_obj = self.hdb._structure_store.get(structure_a)
        self.assertIsNotNone(structure_obj)

        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'internal_fragment_include_runtime_bound_attributes': True,
                'internal_fragment_runtime_attribute_max_count': 2,
                'internal_fragment_runtime_attribute_priority_enabled': True,
                'internal_fragment_runtime_attribute_sort_by_abs_value_desc': True,
                'internal_fragment_runtime_attribute_priority_patterns': ['teacher_reward_signal', 'cfs_*'],
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        restored_profile = self.hdb._structure_retrieval._profile_from_stored_groups(
            list(structure_obj.get('structure', {}).get('sequence_groups', [])),
            cut_engine=self.hdb._cut,
            ext={'kind': 'test_internal_runtime_attr_priority'},
        )
        fragment = self.hdb._structure_retrieval._build_internal_fragment_from_profile(
            owner_id=structure_a,
            owner_kind='st',
            source_group_id='sg_runtime_attr_priority',
            source_phase='unit_test',
            display_text='{A}',
            profile=restored_profile,
            total_er=1.0,
            total_ev=0.2,
            runtime_bound_attribute_units=[
                {'attribute_name': 'stimulus_intensity', 'attribute_value': 1.0},
                {'attribute_name': 'random_numeric_a', 'attribute_value': 0.8},
                {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9},
                {'attribute_name': 'cfs_pressure', 'attribute_value': 0.7},
                {'attribute_name': 'random_numeric_b', 'attribute_value': 0.6},
            ],
        )

        self.assertIsNotNone(fragment)
        packet = self.hdb._cut.build_internal_stimulus_packet(
            [fragment],
            trace_id='trace_internal_runtime_attr_priority',
            tick_id='cycle_internal_runtime_attr_priority',
        )
        attribute_items = [
            item
            for item in packet.get('sa_items', [])
            if (item.get('stimulus', {}) or {}).get('role') == 'attribute'
        ]
        attribute_names = [(item.get('content', {}) or {}).get('attribute_name') for item in attribute_items]
        self.assertIn('teacher_reward_signal', attribute_names)
        self.assertIn('cfs_pressure', attribute_names)
        self.assertNotIn('random_numeric_a', attribute_names)
        self.assertNotIn('random_numeric_b', attribute_names)

    def test_internal_storage_fragment_inherits_runtime_attributes_for_synthetic_round(self):
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg['internal_fragment_include_runtime_bound_attributes'] = True
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        storage_summary = {
            'owner_kind': 'st',
            'owner_id': 'st_anchor_teacher',
            'actions': [
                {
                    'entry_id': 'em_teacher_probe',
                    'type': 'memory_residual',
                    'canonical_signature': 'AB',
                    'canonical_display_text': 'AB',
                    'canonical_sequence_groups': [
                        {
                            'group_index': 0,
                            'source_type': 'storage_residual',
                            'origin_frame_id': 'unit_test',
                            'tokens': ['A', 'B'],
                            'units': [
                                {
                                    'unit_id': 'storage_a',
                                    'object_type': 'sa',
                                    'token': 'A',
                                    'display_text': 'A',
                                    'unit_role': 'feature',
                                    'unit_signature': 'A',
                                    'sequence_index': 0,
                                    'group_index': 0,
                                    'source_group_index': 0,
                                    'source_type': 'storage_residual',
                                    'origin_frame_id': 'unit_test',
                                    'er': 0.0,
                                    'ev': 0.0,
                                    'total_energy': 0.0,
                                    'display_visible': True,
                                    'is_placeholder': False,
                                    'bundle_id': '',
                                    'bundle_anchor_unit_id': '',
                                    'bundle_anchor_signature': '',
                                    'bundle_signature': '',
                                    'bundle_member_unit_ids': [],
                                    'bundle_member_signatures': [],
                                },
                                {
                                    'unit_id': 'storage_b',
                                    'object_type': 'sa',
                                    'token': 'B',
                                    'display_text': 'B',
                                    'unit_role': 'feature',
                                    'unit_signature': 'B',
                                    'sequence_index': 1,
                                    'group_index': 0,
                                    'source_group_index': 0,
                                    'source_type': 'storage_residual',
                                    'origin_frame_id': 'unit_test',
                                    'er': 0.0,
                                    'ev': 0.0,
                                    'total_energy': 0.0,
                                    'display_visible': True,
                                    'is_placeholder': False,
                                    'bundle_id': '',
                                    'bundle_anchor_unit_id': '',
                                    'bundle_anchor_signature': '',
                                    'bundle_signature': '',
                                    'bundle_member_unit_ids': [],
                                    'bundle_member_signatures': [],
                                },
                            ],
                            'csa_bundles': [],
                        }
                    ],
                }
            ],
        }
        fragments = self.hdb._structure_retrieval._build_internal_storage_fragments(
            storage_summary=storage_summary,
            source_group_id='sg_synthetic_runtime_attr',
            source_phase='storage_residual_round',
            fallback_total_er=1.0,
            fallback_total_ev=0.0,
            cut_engine=self.hdb._cut,
            runtime_bound_attribute_units=[
                {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9},
            ],
        )
        self.assertEqual(len(fragments), 1)

        packet = self.hdb._cut.build_internal_stimulus_packet(
            fragments,
            trace_id='trace_internal_storage_runtime_attr',
            tick_id='cycle_internal_storage_runtime_attr',
        )
        attribute_items = [
            item
            for item in packet.get('sa_items', [])
            if (item.get('stimulus', {}) or {}).get('role') == 'attribute'
        ]
        attribute_names = [(item.get('content', {}) or {}).get('attribute_name') for item in attribute_items]
        self.assertIn('teacher_reward_signal', attribute_names)

    def test_anchor_selection_prefers_teacher_runtime_family_when_energy_gap_is_small(self):
        structure_a = self._seed_atomic('A', 'sg_anchor_bonus_seed_a')
        structure_b = self._seed_atomic('B', 'sg_anchor_bonus_seed_b')
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'structure_anchor_runtime_family_bonus_enabled': True,
                'structure_anchor_runtime_family_bonus_patterns': ['teacher_punish_signal'],
                'structure_anchor_runtime_family_bonus_value': 0.7,
                'structure_anchor_runtime_family_bonus_abs_gain': 0.05,
                'structure_anchor_runtime_family_bonus_abs_value_cap': 2.0,
                'structure_anchor_runtime_family_bonus_max_families': 1,
                'structure_anchor_runtime_family_priority_rank_gain': 0.5,
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        cam_items = [
            {
                'structure_id': structure_a,
                'structure_obj': self.hdb._structure_store.get(structure_a),
                'runtime_bound_attribute_units': [],
                'display_text': '{A}',
                'er': 1.2,
                'ev': 0.0,
                'order_index': 0,
            },
            {
                'structure_id': structure_b,
                'structure_obj': self.hdb._structure_store.get(structure_b),
                'runtime_bound_attribute_units': [
                    {'attribute_name': 'teacher_punish_signal', 'attribute_value': 0.85},
                ],
                'display_text': '{B}',
                'er': 1.0,
                'ev': 0.0,
                'order_index': 1,
            },
        ]
        anchor_item = self.hdb._structure_retrieval._select_anchor_item(
            cam_items=cam_items,
            budget_er_map={structure_a: 1.2, structure_b: 1.0},
            budget_ev_map={structure_a: 0.0, structure_b: 0.0},
            temp_anchor_fatigue={},
            skip_structure_ids=set(),
            now_ms=0,
        )
        self.assertIsNotNone(anchor_item)
        self.assertEqual(anchor_item.get('structure_id'), structure_b)
        self.assertGreater(float(anchor_item.get('anchor_runtime_family_bonus', 0.0)), 0.0)
        self.assertIn('teacher_punish_signal', anchor_item.get('anchor_runtime_priority_families', []))

    def test_internal_resolution_prefers_fragment_with_prioritized_runtime_family_when_structure_slots_are_limited(self):
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'internal_fragment_include_runtime_bound_attributes': True,
                'internal_resolution_enabled': True,
                'internal_resolution_max_structures_per_tick': 1,
                'internal_resolution_runtime_family_bonus_enabled': True,
                'internal_resolution_runtime_family_bonus_patterns': ['teacher_reward_signal'],
                'internal_resolution_runtime_family_bonus_value': 0.45,
                'internal_resolution_runtime_family_bonus_abs_gain': 0.05,
                'internal_resolution_runtime_family_bonus_abs_value_cap': 2.0,
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        def _make_fragment(owner_id: str, text: str, runtime_units: list[dict] | None = None) -> dict:
            sequence_groups = [
                {
                    'group_index': 0,
                    'source_type': 'internal',
                    'origin_frame_id': 'unit_test',
                    'tokens': list(text),
                    'units': [
                        {
                            'unit_id': f'{owner_id}_{idx}',
                            'object_type': 'sa',
                            'token': ch,
                            'display_text': ch,
                            'unit_role': 'feature',
                            'unit_signature': ch,
                            'sequence_index': idx,
                            'group_index': 0,
                            'source_group_index': 0,
                            'source_type': 'internal',
                            'origin_frame_id': 'unit_test',
                            'er': 0.0,
                            'ev': 0.0,
                            'total_energy': 0.0,
                            'display_visible': True,
                            'is_placeholder': False,
                            'bundle_id': '',
                            'bundle_anchor_unit_id': '',
                            'bundle_anchor_signature': '',
                            'bundle_signature': '',
                            'bundle_member_unit_ids': [],
                            'bundle_member_signatures': [],
                        }
                        for idx, ch in enumerate(text)
                    ],
                    'csa_bundles': [],
                }
            ]
            return self.hdb._structure_retrieval._build_internal_fragment_from_profile(
                owner_id=owner_id,
                owner_kind='st',
                source_group_id='',
                source_phase='unit_test',
                display_text=text,
                profile={'sequence_groups': sequence_groups, 'flat_tokens': list(text)},
                total_er=1.0,
                total_ev=0.0,
                runtime_bound_attribute_units=runtime_units,
            )

        plain_fragment = _make_fragment('plain_st', 'ABCDEF')
        priority_fragment = _make_fragment(
            'priority_st',
            'UVWXYZ',
            runtime_units=[{'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9}],
        )
        self.assertIsNotNone(plain_fragment)
        self.assertIsNotNone(priority_fragment)

        final_fragments, summary = self.hdb._structure_retrieval._apply_internal_resolution_to_fragments(
            fragments=[plain_fragment, priority_fragment],
            cam_items=[],
            cam_structure_ids=[],
            now_ms=0,
            trace_id='trace_runtime_family_bonus_fragment',
            tick_id='cycle_runtime_family_bonus_fragment',
        )

        self.assertEqual(len(final_fragments), 1)
        self.assertEqual(final_fragments[0].get('source_structure_id'), 'priority_st')
        self.assertEqual(summary.get('runtime_priority_structure_count_total_candidates'), 1)
        self.assertEqual(summary.get('runtime_priority_structure_count'), 1)
        self.assertGreater(float(summary.get('runtime_family_bonus_total', 0.0)), 0.0)

    def test_internal_resolution_trim_rescues_prioritized_runtime_attributes_from_long_fragment(self):
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'internal_fragment_include_runtime_bound_attributes': True,
                'internal_resolution_runtime_attribute_rescue_enabled': True,
                'internal_resolution_runtime_attribute_rescue_patterns': ['teacher_reward_signal', '时间感受', 'cfs_*'],
                'internal_resolution_runtime_attribute_rescue_ratio': 0.25,
                'internal_resolution_runtime_attribute_rescue_min_slots': 1,
                'internal_resolution_runtime_attribute_rescue_max_slots': 1,
                'internal_resolution_runtime_attribute_score_bonus': 0.9,
                'internal_resolution_runtime_attribute_abs_gain': 0.05,
                'internal_resolution_runtime_attribute_abs_value_cap': 2.0,
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        sequence_groups = [
            {
                'group_index': 0,
                'source_type': 'internal',
                'origin_frame_id': 'unit_test',
                'tokens': list('ABCDEFGHIJ'),
                'units': [
                    {
                        'unit_id': f'feature_{idx}',
                        'object_type': 'sa',
                        'token': ch,
                        'display_text': ch,
                        'unit_role': 'feature',
                        'unit_signature': ch,
                        'sequence_index': idx,
                        'group_index': 0,
                        'source_group_index': 0,
                        'source_type': 'internal',
                        'origin_frame_id': 'unit_test',
                        'er': 0.0,
                        'ev': 0.0,
                        'total_energy': 0.0,
                        'display_visible': True,
                        'is_placeholder': False,
                        'bundle_id': '',
                        'bundle_anchor_unit_id': '',
                        'bundle_anchor_signature': '',
                        'bundle_signature': '',
                        'bundle_member_unit_ids': [],
                        'bundle_member_signatures': [],
                    }
                    for idx, ch in enumerate('ABCDEFGHIJ')
                ],
                'csa_bundles': [],
            }
        ]
        fragment = self.hdb._structure_retrieval._build_internal_fragment_from_profile(
            owner_id='long_runtime_attr_st',
            owner_kind='st',
            source_group_id='',
            source_phase='unit_test',
            display_text='ABCDEFGHIJ',
            profile={'sequence_groups': sequence_groups, 'flat_tokens': list('ABCDEFGHIJ')},
            total_er=1.0,
            total_ev=0.0,
            runtime_bound_attribute_units=[
                {'attribute_name': 'stimulus_intensity', 'attribute_value': 1.0},
                {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9},
                {'attribute_name': 'cfs_pressure', 'attribute_value': 0.8},
                {'attribute_name': '时间感受', 'attribute_value': 2.0},
            ],
        )

        self.assertIsNotNone(fragment)
        trimmed_fragment, trim_info = self.hdb._structure_retrieval._trim_internal_fragment_units(
            fragment=fragment,
            target_unit_count=4,
            focus_credit=0.0,
        )
        selected_attribute_names = [
            unit.get('attribute_name')
            for group in trimmed_fragment.get('sequence_groups', [])
            for unit in group.get('units', [])
            if isinstance(unit, dict) and unit.get('unit_role') == 'attribute'
        ]
        self.assertIn('teacher_reward_signal', selected_attribute_names)
        self.assertGreaterEqual(int(trim_info.get('selected_priority_attribute_unit_count', 0)), 1)
        self.assertGreaterEqual(int(trim_info.get('rescued_priority_attribute_count', 0)), 1)

    def test_cam_runtime_priority_sidepath_projects_attribute_only_fragment_for_unrepresented_family(self):
        structure_a = self._seed_atomic('A', 'sg_cam_sidepath_seed_a')
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'internal_cam_runtime_priority_projection_enabled': True,
                'internal_cam_runtime_priority_projection_patterns': ['teacher_reward_signal'],
                'internal_cam_runtime_priority_projection_ratio': 0.1,
                'internal_cam_runtime_priority_projection_min_energy': 0.01,
                'internal_cam_runtime_priority_projection_max_fragments': 2,
                'internal_cam_runtime_priority_projection_require_unrepresented': True,
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        fragments, summary = self.hdb._structure_retrieval._build_cam_runtime_priority_fragments(
            cam_items=[
                {
                    'structure_id': structure_a,
                    'display_text': '{A}',
                    'er': 1.2,
                    'ev': 0.3,
                    'runtime_bound_attribute_units': [
                        {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9},
                    ],
                }
            ],
            budget_er_map={structure_a: 1.2},
            budget_ev_map={structure_a: 0.3},
            existing_fragments=[],
        )

        self.assertEqual(len(fragments), 1)
        self.assertEqual(summary.get('candidate_count'), 1)
        self.assertEqual(summary.get('fragment_count'), 1)
        self.assertEqual(summary.get('projected_family_count'), 1)
        self.assertEqual(summary.get('projected_unit_count'), 1)
        packet = self.hdb._cut.build_internal_stimulus_packet(
            fragments,
            trace_id='trace_cam_runtime_sidepath_project',
            tick_id='cycle_cam_runtime_sidepath_project',
        )
        attribute_items = [
            item
            for item in packet.get('sa_items', [])
            if (item.get('stimulus', {}) or {}).get('role') == 'attribute'
        ]
        attribute_names = [(item.get('content', {}) or {}).get('attribute_name') for item in attribute_items]
        self.assertIn('teacher_reward_signal', attribute_names)

    def test_cam_runtime_priority_sidepath_skips_family_already_represented_by_existing_fragment(self):
        structure_a = self._seed_atomic('A', 'sg_cam_sidepath_seed_repr_a')
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'internal_cam_runtime_priority_projection_enabled': True,
                'internal_cam_runtime_priority_projection_patterns': ['teacher_reward_signal'],
                'internal_cam_runtime_priority_projection_ratio': 0.1,
                'internal_cam_runtime_priority_projection_min_energy': 0.01,
                'internal_cam_runtime_priority_projection_max_fragments': 2,
                'internal_cam_runtime_priority_projection_require_unrepresented': True,
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        existing_fragment = self.hdb._structure_retrieval._build_internal_fragment_from_profile(
            owner_id=structure_a,
            owner_kind='st',
            source_group_id='',
            source_phase='unit_test_existing_runtime_fragment',
            display_text='teacher_sidepath_existing',
            profile={'sequence_groups': [], 'flat_tokens': []},
            total_er=0.2,
            total_ev=0.0,
            runtime_bound_attribute_units=[
                {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.7},
            ],
            force_runtime_attribute_groups=True,
        )
        self.assertIsNotNone(existing_fragment)

        fragments, summary = self.hdb._structure_retrieval._build_cam_runtime_priority_fragments(
            cam_items=[
                {
                    'structure_id': structure_a,
                    'display_text': '{A}',
                    'er': 1.2,
                    'ev': 0.0,
                    'runtime_bound_attribute_units': [
                        {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9},
                    ],
                }
            ],
            budget_er_map={structure_a: 1.2},
            budget_ev_map={structure_a: 0.0},
            existing_fragments=[existing_fragment],
        )

        self.assertEqual(fragments, [])
        self.assertEqual(summary.get('candidate_count'), 0)
        self.assertEqual(summary.get('fragment_count'), 0)

    def test_cam_only_path_projects_runtime_priority_sidepath_from_ref_snapshot(self):
        retrieval_cfg = dict(self.hdb._structure_retrieval._config)
        retrieval_cfg.update(
            {
                'internal_fragment_include_runtime_bound_attributes': False,
                'internal_cam_runtime_priority_projection_enabled': True,
                'internal_cam_runtime_priority_projection_patterns': ['teacher_reward_signal'],
                'internal_cam_runtime_priority_projection_ratio': 0.1,
                'internal_cam_runtime_priority_projection_min_energy': 0.01,
                'internal_cam_runtime_priority_projection_max_fragments': 1,
                'internal_cam_runtime_priority_projection_require_unrepresented': True,
            }
        )
        self.hdb._structure_retrieval.update_config(retrieval_cfg)

        item = {
            'ref_object_type': 'st',
            'ref_object_id': 'st_cam_only_runtime_attr',
            'display': 'A',
            'er': 1.0,
            'ev': 0.0,
            'cp_abs': 0.0,
            'ref_snapshot': {
                'content_display': 'A',
                'flat_tokens': ['A'],
                'sequence_groups': [
                    {
                        'group_index': 0,
                        'source_type': 'current',
                        'origin_frame_id': 'frame_cam_only_runtime_attr',
                        'tokens': ['A'],
                        'units': [
                            {
                                'unit_id': 'cam_only_feature_0',
                                'object_type': 'sa',
                                'token': 'A',
                                'display_text': 'A',
                                'unit_role': 'feature',
                                'unit_signature': 'A',
                                'sequence_index': 0,
                                'group_index': 0,
                                'source_group_index': 0,
                                'source_type': 'current',
                                'origin_frame_id': 'frame_cam_only_runtime_attr',
                                'er': 0.0,
                                'ev': 0.0,
                                'total_energy': 0.0,
                                'display_visible': True,
                                'is_placeholder': False,
                                'bundle_id': '',
                                'bundle_anchor_unit_id': '',
                                'bundle_anchor_signature': '',
                                'bundle_signature': '',
                                'bundle_member_unit_ids': [],
                                'bundle_member_signatures': [],
                            }
                        ],
                        'csa_bundles': [],
                    }
                ],
                'runtime_bound_attribute_units': [
                    {'attribute_name': 'teacher_reward_signal', 'attribute_value': 0.9},
                ],
            },
        }
        result = self.hdb._structure_retrieval._run_cam_internal_stimulus_only(
            items=[item],
            trace_id='trace_cam_only_runtime_sidepath',
            tick_id='cycle_cam_only_runtime_sidepath',
            cut_engine=self.hdb._cut,
        )
        summary = result.get('cam_runtime_priority_projection', {})
        self.assertEqual(summary.get('candidate_count'), 1)
        self.assertEqual(summary.get('fragment_count'), 1)

        packet = self.hdb._cut.build_internal_stimulus_packet(
            result.get('internal_stimulus_fragments', []),
            trace_id='trace_cam_only_runtime_sidepath_packet',
            tick_id='cycle_cam_only_runtime_sidepath_packet',
        )
        attribute_items = [
            item
            for item in packet.get('sa_items', [])
            if (item.get('stimulus', {}) or {}).get('role') == 'attribute'
        ]
        attribute_names = [(item.get('content', {}) or {}).get('attribute_name') for item in attribute_items]
        self.assertIn('teacher_reward_signal', attribute_names)


if __name__ == '__main__':
    unittest.main()
