# -*- coding: utf-8 -*-

import os
import shutil
import tempfile
import unittest

from hdb import HDB
from hdb._context_metadata import extract_context_metadata
from hdb._owner_runtime_budget import build_owner_runtime_candidate_view


class TestHDBBasic(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_basic_')
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _packet(self, text: str) -> dict:
        sa_items = []
        for idx, ch in enumerate(text):
            sa_items.append({
                'id': f'sa_{idx}',
                'object_type': 'sa',
                'content': {'raw': ch, 'display': ch, 'normalized': ch},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': idx}},
            })
        return {
            'id': 'spkt_basic',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_basic', 'sa_ids': [item['id'] for item in sa_items], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _csa_packet(self, anchor: str, attrs: list[str], *, packet_id: str) -> dict:
        anchor_id = f'{packet_id}_sa_anchor'
        sa_items = [
            {
                'id': anchor_id,
                'object_type': 'sa',
                'content': {'raw': anchor, 'display': anchor, 'normalized': anchor},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': 0}},
            }
        ]
        member_ids = [anchor_id]
        for index, attr in enumerate(attrs, start=1):
            attr_id = f'{packet_id}_sa_attr_{index}'
            sa_items.append(
                {
                    'id': attr_id,
                    'object_type': 'sa',
                    'content': {'raw': attr, 'display': attr, 'normalized': attr},
                    'stimulus': {'role': 'attribute', 'modality': 'text'},
                    'energy': {'er': 0.2, 'ev': 0.0},
                    'source': {'parent_ids': [anchor_id]},
                    'ext': {'packet_context': {'sequence_index': index}},
                }
            )
            member_ids.append(attr_id)
        csa_id = f'{packet_id}_csa'
        csa_items = [
            {
                'id': csa_id,
                'object_type': 'csa',
                'anchor_sa_id': anchor_id,
                'member_sa_ids': member_ids,
                'content': {'display': f'CSA[{anchor}]', 'raw': anchor},
                'energy': {'er': 1.0 + 0.2 * len(attrs), 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': len(sa_items)}},
            }
        ]
        return {
            'id': packet_id,
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': csa_items,
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': f'frame_{packet_id}', 'sa_ids': [anchor_id], 'csa_ids': [csa_id]}
            ],
            'energy_summary': {'current_total_er': 1.0 + 0.2 * len(attrs), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _grouped_packet(self, groups: list[str], *, packet_id: str) -> dict:
        sa_items = []
        grouped = []
        sequence = 0
        for group_index, text in enumerate(groups):
            group_sa_ids = []
            for ch in text:
                sa_id = f'{packet_id}_sa_{group_index}_{sequence}'
                sa_items.append(
                    {
                        'id': sa_id,
                        'object_type': 'sa',
                        'content': {'raw': ch, 'display': ch, 'normalized': ch},
                        'stimulus': {'role': 'feature', 'modality': 'text'},
                        'energy': {'er': 1.0, 'ev': 0.0},
                        'ext': {'packet_context': {'group_index': group_index, 'sequence_index': sequence, 'source_type': 'current'}},
                    }
                )
                group_sa_ids.append(sa_id)
                sequence += 1
            grouped.append(
                {
                    'group_index': group_index,
                    'source_type': 'current',
                    'origin_frame_id': f'frame_{packet_id}_{group_index}',
                    'sa_ids': group_sa_ids,
                    'csa_ids': [],
                }
            )
        return {
            'id': packet_id,
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': grouped,
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _grouped_numeric_packet(self, groups: list[tuple[str, float]], *, packet_id: str) -> dict:
        sa_items = []
        csa_items = []
        grouped = []
        sequence = 0
        origin_frame_id = f'frame_{packet_id}'
        for group_index, (anchor_text, intensity) in enumerate(groups):
            anchor_id = f'{packet_id}_sa_anchor_{group_index}'
            attr_id = f'{packet_id}_sa_attr_{group_index}'
            csa_id = f'{packet_id}_csa_{group_index}'
            sa_items.append(
                {
                    'id': anchor_id,
                    'object_type': 'sa',
                    'content': {'raw': anchor_text, 'display': anchor_text, 'normalized': anchor_text},
                    'stimulus': {'role': 'feature', 'modality': 'text'},
                    'energy': {'er': float(intensity), 'ev': 0.0},
                    'ext': {'packet_context': {'group_index': group_index, 'sequence_index': sequence, 'source_type': 'current'}},
                }
            )
            sequence += 1
            sa_items.append(
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
                    'ext': {'packet_context': {'group_index': group_index, 'sequence_index': sequence, 'source_type': 'current'}},
                }
            )
            sequence += 1
            csa_items.append(
                {
                    'id': csa_id,
                    'object_type': 'csa',
                    'anchor_sa_id': anchor_id,
                    'member_sa_ids': [anchor_id, attr_id],
                    'content': {'display': f'CSA[{anchor_text}]', 'raw': anchor_text},
                    'energy': {'er': float(intensity) * 1.25, 'ev': 0.0},
                    'ext': {'packet_context': {'group_index': group_index, 'sequence_index': sequence}},
                }
            )
            grouped.append(
                {
                    'group_index': group_index,
                    'source_type': 'current',
                    'origin_frame_id': origin_frame_id,
                    'sa_ids': [anchor_id],
                    'csa_ids': [csa_id],
                }
            )
        return {
            'id': packet_id,
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': csa_items,
            'grouped_sa_sequences': grouped,
            'energy_summary': {'current_total_er': float(sum(item['energy']['er'] for item in sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _packet_from_group_specs(self, group_specs: list[dict], *, packet_id: str) -> dict:
        sa_items = []
        csa_items = []
        grouped = []
        sequence = 0
        for group_index, spec in enumerate(group_specs):
            source_type = str(spec.get('source_type', 'current'))
            origin_frame_id = str(spec.get('origin_frame_id', f'frame_{packet_id}_{group_index}'))
            feature_ids = []
            csa_member_ids = []
            anchor_id = ''
            default_feature_er = float(spec.get('feature_er', spec.get('attr_value', 1.0) or 1.0))
            for feature_index, feature_text in enumerate(spec.get('features', [])):
                feature_id = f'{packet_id}_sa_feature_{group_index}_{feature_index}'
                if not anchor_id:
                    anchor_id = feature_id
                sa_items.append(
                    {
                        'id': feature_id,
                        'object_type': 'sa',
                        'content': {'raw': feature_text, 'display': feature_text, 'normalized': feature_text},
                        'stimulus': {'role': 'feature', 'modality': 'text'},
                        'energy': {'er': default_feature_er, 'ev': 0.0},
                        'ext': {
                            'packet_context': {
                                'group_index': group_index,
                                'sequence_index': sequence,
                                'source_type': source_type,
                            }
                        },
                    }
                )
                feature_ids.append(feature_id)
                csa_member_ids.append(feature_id)
                sequence += 1

            csa_ids = []
            attr_name = spec.get('attr_name')
            if attr_name and anchor_id:
                attr_value = float(spec.get('attr_value', 0.0))
                attr_id = f'{packet_id}_sa_attr_{group_index}'
                sa_items.append(
                    {
                        'id': attr_id,
                        'object_type': 'sa',
                        'content': {
                            'raw': f'{attr_name}:{attr_value}',
                            'display': f'{attr_name}:{attr_value}',
                            'normalized': f'{attr_name}:{attr_value}',
                            'value_type': 'numerical',
                            'attribute_name': attr_name,
                            'attribute_value': attr_value,
                        },
                        'stimulus': {'role': 'attribute', 'modality': 'text'},
                        'energy': {'er': float(spec.get('attr_er', attr_value * 0.25)), 'ev': 0.0},
                        'source': {'parent_ids': [anchor_id]},
                        'ext': {
                            'packet_context': {
                                'group_index': group_index,
                                'sequence_index': sequence,
                                'source_type': source_type,
                            }
                        },
                    }
                )
                csa_member_ids.append(attr_id)
                sequence += 1
                csa_id = f'{packet_id}_csa_{group_index}'
                csa_items.append(
                    {
                        'id': csa_id,
                        'object_type': 'csa',
                        'anchor_sa_id': anchor_id,
                        'member_sa_ids': list(csa_member_ids),
                        'content': {
                            'display': f'CSA[{spec.get("features", [""])[0]}]',
                            'raw': spec.get('features', [''])[0],
                        },
                        'energy': {'er': float(spec.get('csa_er', default_feature_er + float(spec.get('attr_er', attr_value * 0.25)))), 'ev': 0.0},
                        'ext': {'packet_context': {'group_index': group_index, 'sequence_index': sequence}},
                    }
                )
                csa_ids.append(csa_id)

            grouped.append(
                {
                    'group_index': group_index,
                    'source_type': source_type,
                    'origin_frame_id': origin_frame_id,
                    'sa_ids': feature_ids,
                    'csa_ids': csa_ids,
                }
            )

        return {
            'id': packet_id,
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': csa_items,
            'grouped_sa_sequences': grouped,
            'energy_summary': {'current_total_er': float(sum(item['energy']['er'] for item in sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _store_packet_as_structure(self, packet: dict, *, trace_id: str) -> dict:
        profile = self.hdb._cut.build_sequence_profile_from_stimulus_packet(packet)
        payload = self.hdb._cut.make_structure_payload_from_profile(
            profile,
            confidence=0.9,
            ext={'kind': 'test_seed', 'relation_type': 'test_seed'},
        )
        structure_obj, _ = self.hdb._structure_store.create_structure(
            structure_payload=payload,
            trace_id=trace_id,
            tick_id=trace_id,
            origin='test_seed',
            origin_id=packet.get('id', trace_id),
            parent_ids=[],
        )
        self.hdb._pointer_index.register_structure(structure_obj)
        return structure_obj

    def _link_owner_to_structure(self, *, owner_structure_id: str, target_structure: dict, residual_incoming_signature: str = '') -> dict:
        entry = self.hdb._structure_store.add_diff_entry(
            owner_structure_id,
            target_id=target_structure['id'],
            content_signature=target_structure.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature=residual_incoming_signature,
            ext={'relation_type': 'incoming_extension', 'source_packet_id': 'test_seed'},
        )
        self.assertIsNotNone(entry)
        return entry

    def _find_structure_by_flat_tokens(self, expected_tokens: list[str]) -> dict | None:
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == list(expected_tokens):
                return structure_obj
        return None

    def _owner_db_entries(self, owner_structure_id: str, *, entry_type: str | None = None, relation_type: str | None = None):
        owner_db = self.hdb._structure_store.get_db_by_owner(owner_structure_id)
        self.assertIsNotNone(owner_db)
        entries = list(owner_db.get('diff_table', []))
        if entry_type is not None:
            entries = [entry for entry in entries if entry.get('entry_type', '') == entry_type]
        if relation_type is not None:
            entries = [entry for entry in entries if entry.get('ext', {}).get('relation_type') == relation_type]
        return owner_db, entries

    def test_stimulus_level_creates_structure_and_snapshot(self):
        result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好'), trace_id='basic_t1')
        self.assertTrue(result['success'])
        self.assertGreaterEqual(len(result['data'].get('seeded_atomic_structure_ids', [])), 1)

        snapshot = self.hdb.get_hdb_snapshot(trace_id='basic_snap')
        self.assertGreaterEqual(
            snapshot['data']['summary']['structure_count'],
            len(result['data'].get('seeded_atomic_structure_ids', [])),
        )
        self.assertEqual(snapshot['data']['summary']['episodic_count'], 1)

    def test_exact_match_first_pass_only_writes_owner_residual_context(self):
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('我是'),
            trace_id='basic_ext_1',
            max_rounds=1,
        )
        self.assertTrue(result['success'])
        round_details = result['data']['debug']['round_details']
        self.assertGreaterEqual(len(round_details), 1)
        first_round = round_details[0]
        self.assertIn('我', first_round['remaining_tokens_after'])
        self.assertGreater(float(first_round['effective_transfer_fraction']), 0.7)
        self.assertIsNone(first_round.get('created_fresh_structure'))
        self.assertIsNone(first_round.get('created_common_structure'))
        self.assertIsNotNone(first_round.get('created_residual_structure'))

        atomic_wo = self._find_structure_by_flat_tokens(['我'])
        atomic_shi = self._find_structure_by_flat_tokens(['是'])
        self.assertIsNotNone(atomic_wo)
        self.assertIsNotNone(atomic_shi)

        full_structure = [
            structure_obj for structure_obj in self.hdb._structure_store.iter_structures()
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == ['我', '是']
        ]
        self.assertEqual(len(full_structure), 0)

        _, residual_entries = self._owner_db_entries(
            atomic_wo['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertEqual(len(residual_entries), 1)
        residual_entry = residual_entries[0]
        expected_profile = self.hdb._cut.build_sequence_profile_from_stimulus_packet(self._packet('我是'))
        self.assertEqual(
            residual_entry.get('canonical_content_signature', ''),
            expected_profile.get('content_signature', ''),
        )
        self.assertIn('SELF[', residual_entry.get('display_text', ''))
        self.assertNotIn('SELF[', residual_entry.get('canonical_display_text', ''))
        self.assertTrue((residual_entry.get('memory_refs') or [''])[0].startswith('em_'))

        _, shi_entries = self._owner_db_entries(
            atomic_shi['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertFalse(shi_entries)

    def test_partial_overlap_does_not_create_direct_cut_entry_without_owner_local_match(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你'), trace_id='basic_cut_atomic_seed', max_rounds=1)
        source_structure = self._store_packet_as_structure(self._packet('你好呀'), trace_id='basic_cut_seed_structure')
        atomic_you = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == ['你']:
                atomic_you = structure_obj
                break
        self.assertIsNotNone(atomic_you)
        self._link_owner_to_structure(owner_structure_id=atomic_you['id'], target_structure=source_structure)
        result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好！'), trace_id='basic_cut_match')
        self.assertTrue(result['success'])

        owner_db = self.hdb._structure_store.get_db_by_owner(source_structure['id'])
        self.assertIsNotNone(owner_db)
        expected_existing_signature = self.hdb._cut.sequence_groups_to_signature([{'group_index': 0, 'tokens': ['呀']}])
        expected_incoming_signature = self.hdb._cut.sequence_groups_to_signature([{'group_index': 0, 'tokens': ['！']}])
        matching_entries = [
            entry for entry in owner_db.get('diff_table', [])
            if entry.get('residual_existing_signature') == expected_existing_signature and entry.get('residual_incoming_signature') == expected_incoming_signature
        ]
        # 旧的“直接 partial overlap 切割”路径已经移除。
        # 现在只有命中 owner 后，才会在 owner-local residual 语义里做残差归一化与共同结构发现。
        self.assertEqual(len(matching_entries), 0)

    def test_identical_residual_context_reinforces_existing_owner_entry(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('我是'),
            trace_id='basic_merge_seed_1',
            max_rounds=1,
        )
        atomic_wo = self._find_structure_by_flat_tokens(['我'])
        self.assertIsNotNone(atomic_wo)

        _, before_entries = self._owner_db_entries(
            atomic_wo['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertEqual(len(before_entries), 1)
        before_weight = before_entries[0].get('base_weight', 0.0)
        before_match_count = before_entries[0].get('match_count_total', 0)
        before_memory_count = len(before_entries[0].get('memory_refs', []))

        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('我是'),
            trace_id='basic_merge_seed_2',
            max_rounds=1,
        )

        _, after_entries = self._owner_db_entries(
            atomic_wo['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertEqual(len(after_entries), 1)
        self.assertGreater(after_entries[0].get('base_weight', 0.0), before_weight)
        self.assertGreater(after_entries[0].get('match_count_total', 0), before_match_count)
        self.assertEqual(len(after_entries[0].get('memory_refs', [])), before_memory_count + 1)

    def test_atomic_match_score_uses_energy_coverage_s_curve(self):
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('ABC'),
            trace_id='basic_score_curve',
            max_rounds=1,
        )
        self.assertTrue(result['success'])
        first_round = result['data']['debug']['round_details'][0]
        self.assertGreater(float(first_round['selected_match']['competition_score']), 0.7)

    def test_atomic_match_score_uses_whole_remaining_packet_as_denominator(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('A'),
            trace_id='whole_remaining_seed',
            max_rounds=1,
        )
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._grouped_packet(['A', 'B', 'C'], packet_id='whole_remaining_pkt'),
            trace_id='whole_remaining_trace',
            max_rounds=1,
        )
        self.assertTrue(result['success'])
        first_round = result['data']['debug']['round_details'][0]
        selected = first_round['selected_match']
        self.assertIsNotNone(selected)
        self.assertEqual(selected['display_text'], '{A}')
        self.assertLess(float(selected['competition_score']), 1.0)
        self.assertGreater(float(selected['competition_score']), 0.7)

    def test_partial_structure_does_not_participate_in_full_inclusion_competition(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你'), trace_id='strict_seed_anchor', max_rounds=1)
        plain_structure = self._store_packet_as_structure(self._packet('你好呀'), trace_id='strict_seed_plain')
        exclaim_structure = self._store_packet_as_structure(self._packet('你好呀！'), trace_id='strict_seed_exclaim')
        atomic_you = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == ['你']:
                atomic_you = structure_obj
                break
        self.assertIsNotNone(atomic_you)
        self._link_owner_to_structure(owner_structure_id=atomic_you['id'], target_structure=plain_structure)
        self._link_owner_to_structure(owner_structure_id=atomic_you['id'], target_structure=exclaim_structure)

        result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好呀'), trace_id='strict_match_plain')
        self.assertTrue(result['success'])

        round_details = result['data']['debug']['round_details']
        self.assertGreaterEqual(len(round_details), 1)
        first_round = round_details[0]
        selected = first_round['selected_match']
        self.assertIsNotNone(selected)
        self.assertEqual(selected['structure_id'], plain_structure['id'])
        self.assertLessEqual(float(selected['competition_score']), 1.0)
        self.assertGreater(float(selected['competition_score']), 0.9)

        exclaim_candidates = [
            detail for detail in first_round['candidate_details']
            if detail.get('structure_id') == exclaim_structure['id']
        ]
        self.assertEqual(len(exclaim_candidates), 1)
        self.assertFalse(exclaim_candidates[0]['full_structure_included'])
        self.assertLessEqual(float(exclaim_candidates[0]['competition_score']), float(selected['competition_score']))

    def test_csa_structure_does_not_fully_match_when_attribute_bundle_is_missing(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('A'), trace_id='csa_anchor_seed', max_rounds=1)
        csa_structure = self._store_packet_as_structure(
            self._csa_packet('A', ['x'], packet_id='csa_seed'),
            trace_id='csa_seed_trace',
        )
        atomic_a = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == ['A']:
                atomic_a = structure_obj
                break
        self.assertIsNotNone(atomic_a)
        self._link_owner_to_structure(owner_structure_id=atomic_a['id'], target_structure=csa_structure)
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._csa_packet('A', [], packet_id='csa_incoming'),
            trace_id='csa_incoming_trace',
        )
        self.assertTrue(result['success'])

        round_details = result['data']['debug']['round_details']
        self.assertGreaterEqual(len(round_details), 1)
        first_round = round_details[0]
        bundle_candidates = [
            detail
            for detail in first_round['candidate_details']
            if detail.get('structure_id') == csa_structure['id']
        ]
        self.assertTrue(bundle_candidates)
        self.assertNotEqual(first_round['selected_match']['structure_id'], csa_structure['id'])
        self.assertTrue(any(float(detail.get('v2_attribute_anchor_score', 0.0)) < 1.0 for detail in bundle_candidates))
        self.assertTrue(any(float(detail.get('competition_score', 0.0)) <= float(first_round['selected_match'].get('competition_score', 0.0)) for detail in bundle_candidates))

    def test_residual_context_descends_into_existing_local_common_structure(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('ABX'), trace_id='residual_seed_1')
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('ABY'), trace_id='residual_seed_2')
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('ABZ'), trace_id='residual_seed_3')

        atomic_a = self._find_structure_by_flat_tokens(['A'])
        self.assertIsNotNone(atomic_a)

        _, owner_common_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='structure_ref',
            relation_type='residual_context_common',
        )
        self.assertEqual(len(owner_common_entries), 1)

        common_structure = self.hdb._structure_store.get(owner_common_entries[0]['target_id'])
        self.assertIsNotNone(common_structure)
        common_tokens = list(common_structure.get('structure', {}).get('flat_tokens', []))
        self.assertEqual(common_tokens, ['A', 'B'])
        self.assertFalse(any(token.startswith('SELF[') for token in common_tokens))
        common_context = extract_context_metadata(common_structure)
        self.assertEqual(common_context['context_ref_object_id'], '')
        self.assertEqual(common_context['context_owner_structure_id'], '')
        self.assertEqual(common_context['context_path_ids'], [])
        common_ext = common_structure.get('structure', {}).get('ext', {})
        self.assertTrue(common_ext.get('identity_context_free'))
        self.assertEqual(common_ext.get('provenance_owner_structure_id'), atomic_a['id'])

        _, child_entries = self._owner_db_entries(
            common_structure['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertEqual(len(child_entries), 3)

        child_canonical_displays = {entry.get('canonical_display_text', '') for entry in child_entries}
        self.assertIn('{A + B + X}', child_canonical_displays)
        self.assertIn('{A + B + Y}', child_canonical_displays)
        self.assertIn('{A + B + Z}', child_canonical_displays)
        self.assertTrue(all('SELF[' not in entry.get('canonical_display_text', '') for entry in child_entries))

    def test_residual_parent_match_reinforces_owner_entry_and_descends_new_tail(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='parent_seed_ab',
            max_rounds=1,
        )
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('ABC'),
            trace_id='parent_seed_abc',
            max_rounds=1,
        )

        atomic_a = self._find_structure_by_flat_tokens(['A'])
        self.assertIsNotNone(atomic_a)

        _, owner_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='structure_ref',
            relation_type='residual_context_common',
        )
        self.assertEqual(len(owner_entries), 1)
        parent_entry = owner_entries[0]
        self.assertGreater(parent_entry.get('base_weight', 0.0), 0.0)

        parent_structure = self.hdb._structure_store.get(parent_entry['target_id'])
        self.assertIsNotNone(parent_structure)
        parent_tokens = list(parent_structure.get('structure', {}).get('flat_tokens', []))
        self.assertEqual(parent_tokens, ['A', 'B'])

        _, child_entries = self._owner_db_entries(
            parent_structure['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertEqual(len(child_entries), 1)
        self.assertEqual(child_entries[0].get('canonical_display_text', ''), '{A + B + C}')

    def test_owner_local_residual_listing_reuses_runtime_cache_until_entry_changes(self):
        seed_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='owner_local_cache_seed',
            max_rounds=1,
        )
        self.assertTrue(seed_result['success'])

        atomic_a = self._find_structure_by_flat_tokens(['A'])
        self.assertIsNotNone(atomic_a)
        owner_db = self.hdb._structure_store.get_db_by_owner(atomic_a['id'])
        self.assertIsNotNone(owner_db)

        _, raw_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertGreaterEqual(len(raw_entries), 1)

        engine = self.hdb._stimulus
        original_ensure_profiles = engine._ensure_raw_residual_entry_profiles
        call_count = {'value': 0}

        def _counted_ensure_profiles(**kwargs):
            call_count['value'] += 1
            return original_ensure_profiles(**kwargs)

        engine._runtime_cache = {
            'raw_residual_entry_profiles': {},
            'structure_profiles': {},
            'owner_local_residual_items': {},
            'owner_local_residual_versions': {},
        }
        engine._ensure_raw_residual_entry_profiles = _counted_ensure_profiles
        try:
            first_items = engine._list_owner_local_residual_items(
                owner_db=owner_db,
                owner_structure_id=atomic_a['id'],
                structure_store=self.hdb._structure_store,
                cut_engine=self.hdb._cut,
            )
            first_call_count = call_count['value']
            self.assertGreaterEqual(first_call_count, 1)
            self.assertTrue(first_items)

            second_items = engine._list_owner_local_residual_items(
                owner_db=owner_db,
                owner_structure_id=atomic_a['id'],
                structure_store=self.hdb._structure_store,
                cut_engine=self.hdb._cut,
            )
            self.assertEqual(call_count['value'], first_call_count)
            self.assertEqual(
                [item.get('entry_id', '') for item in first_items],
                [item.get('entry_id', '') for item in second_items],
            )

            raw_entries[0]['recent_gain'] = round(float(raw_entries[0].get('recent_gain', 1.0)) + 0.25, 8)
            raw_entries[0]['last_updated_at'] = int(raw_entries[0].get('last_updated_at', 0) or 0) + 1
            engine._invalidate_owner_local_residual_cache(owner_structure_id=atomic_a['id'])

            third_items = engine._list_owner_local_residual_items(
                owner_db=owner_db,
                owner_structure_id=atomic_a['id'],
                structure_store=self.hdb._structure_store,
                cut_engine=self.hdb._cut,
            )
            self.assertGreater(call_count['value'], first_call_count)
            self.assertEqual(
                [item.get('entry_id', '') for item in first_items],
                [item.get('entry_id', '') for item in third_items],
            )
        finally:
            engine._ensure_raw_residual_entry_profiles = original_ensure_profiles
            engine._runtime_cache = None

    def test_shadow_raw_residual_skip_does_not_materialize_profiles_when_promotion_off(self):
        seed_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='shadow_skip_seed',
            max_rounds=1,
        )
        self.assertTrue(seed_result['success'])

        atomic_a = self._find_structure_by_flat_tokens(['A'])
        self.assertIsNotNone(atomic_a)
        owner_db = self.hdb._structure_store.get_db_by_owner(atomic_a['id'])
        self.assertIsNotNone(owner_db)

        _, raw_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertGreaterEqual(len(raw_entries), 1)

        engine = self.hdb._stimulus
        original_ensure_profiles = engine._ensure_raw_residual_entry_profiles
        call_count = {'value': 0}

        def _counted_ensure_profiles(**kwargs):
            call_count['value'] += 1
            return original_ensure_profiles(**kwargs)

        engine._runtime_cache = {
            'raw_residual_entry_profiles': {},
            'structure_profiles': {},
            'owner_local_residual_items': {},
            'owner_local_residual_versions': {},
            'metrics': {
                'shadow_raw_residual_candidate_count': 0,
                'shadow_raw_residual_skipped_count': 0,
            },
        }
        engine._ensure_raw_residual_entry_profiles = _counted_ensure_profiles
        old_promotion_enabled = self.hdb._config.get('stimulus_residual_memory_promotion_enabled')
        old_skip_enabled = self.hdb._config.get('stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled')
        self.hdb._config['stimulus_residual_memory_promotion_enabled'] = False
        self.hdb._config['stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled'] = True
        try:
            details, promoted, entry_lookup = engine._build_local_shadow_raw_residual_candidate_details(
                owner_match={'structure_id': atomic_a['id']},
                incoming_profile=self.hdb._cut.build_sequence_profile_from_stimulus_packet(self._packet('AB')),
                competition_units=[],
                structure_store=self.hdb._structure_store,
                pointer_index=self.hdb._pointer_index,
                cut_engine=self.hdb._cut,
                anchor_token='A',
                min_existing_length=1,
            )
            self.assertEqual(details, [])
            self.assertEqual(promoted, [])
            self.assertEqual(entry_lookup, {})
            self.assertEqual(call_count['value'], 0)
            metrics = engine._runtime_cache.get('metrics', {})
            self.assertEqual(metrics.get('shadow_raw_residual_candidate_count'), len(raw_entries))
            self.assertEqual(metrics.get('shadow_raw_residual_skipped_count'), len(raw_entries))
        finally:
            engine._ensure_raw_residual_entry_profiles = original_ensure_profiles
            engine._runtime_cache = None
            if old_promotion_enabled is None:
                self.hdb._config.pop('stimulus_residual_memory_promotion_enabled', None)
            else:
                self.hdb._config['stimulus_residual_memory_promotion_enabled'] = old_promotion_enabled
            if old_skip_enabled is None:
                self.hdb._config.pop('stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled', None)
            else:
                self.hdb._config['stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled'] = old_skip_enabled

    def test_shadow_raw_residual_cap_materializes_only_kept_entries(self):
        seed_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._grouped_packet(['A', 'B'], packet_id='shadow_cap_seed_pkt'),
            trace_id='shadow_cap_seed',
            max_rounds=6,
        )
        self.assertTrue(seed_result['success'])

        current_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._grouped_packet(['B', 'A', 'C'], packet_id='shadow_cap_current_pkt'),
            trace_id='shadow_cap_current',
            max_rounds=6,
        )
        self.assertTrue(current_result['success'])

        atomic_a = self._find_structure_by_flat_tokens(['A'])
        self.assertIsNotNone(atomic_a)
        owner_db, raw_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertGreaterEqual(len(raw_entries), 2)

        raw_entries_sorted = sorted(
            list(raw_entries),
            key=lambda entry: (
                -float(self.hdb._stimulus._weight.entry_runtime_weight(entry) or 0.0),
                -float(entry.get('base_weight', 0.0) or 0.0),
                str(entry.get('entry_id', '')),
            ),
        )
        expected_entry_id = str(raw_entries_sorted[0].get('entry_id', ''))

        engine = self.hdb._stimulus
        original_ensure_profiles = engine._ensure_raw_residual_entry_profiles
        call_entry_ids = []

        def _counted_ensure_profiles(**kwargs):
            entry = kwargs.get('entry', {})
            call_entry_ids.append(str(entry.get('entry_id', '')))
            return original_ensure_profiles(**kwargs)

        engine._runtime_cache = {
            'raw_residual_entry_profiles': {},
            'structure_profiles': {},
            'owner_local_residual_items': {},
            'owner_local_residual_versions': {},
            'metrics': {
                'shadow_raw_residual_candidate_count': 0,
                'shadow_raw_residual_candidate_pruned_count': 0,
            },
        }
        old_shadow_cap = self.hdb._config.get('stimulus_shadow_raw_residual_candidate_max_per_owner')
        old_promotion_enabled = self.hdb._config.get('stimulus_residual_memory_promotion_enabled')
        old_skip_enabled = self.hdb._config.get('stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled')
        engine._ensure_raw_residual_entry_profiles = _counted_ensure_profiles
        self.hdb._config['stimulus_shadow_raw_residual_candidate_max_per_owner'] = 1
        self.hdb._config['stimulus_residual_memory_promotion_enabled'] = False
        self.hdb._config['stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled'] = False
        try:
            details, promoted, entry_lookup = engine._build_local_shadow_raw_residual_candidate_details(
                owner_match={'structure_id': atomic_a['id']},
                incoming_profile=self.hdb._cut.build_sequence_profile_from_stimulus_packet(self._packet('ABC')),
                competition_units=[],
                structure_store=self.hdb._structure_store,
                pointer_index=self.hdb._pointer_index,
                cut_engine=self.hdb._cut,
                anchor_token='A',
                min_existing_length=1,
            )
            self.assertEqual(len(call_entry_ids), 1)
            self.assertEqual(call_entry_ids[0], expected_entry_id)
            self.assertLessEqual(len(details), 1)
            self.assertEqual(promoted, [])
            self.assertEqual(entry_lookup, {})
            metrics = engine._runtime_cache.get('metrics', {})
            self.assertEqual(metrics.get('shadow_raw_residual_candidate_count'), len(raw_entries))
            self.assertEqual(metrics.get('shadow_raw_residual_candidate_pruned_count'), len(raw_entries) - 1)
        finally:
            engine._ensure_raw_residual_entry_profiles = original_ensure_profiles
            engine._runtime_cache = None
            if old_shadow_cap is None:
                self.hdb._config.pop('stimulus_shadow_raw_residual_candidate_max_per_owner', None)
            else:
                self.hdb._config['stimulus_shadow_raw_residual_candidate_max_per_owner'] = old_shadow_cap
            if old_promotion_enabled is None:
                self.hdb._config.pop('stimulus_residual_memory_promotion_enabled', None)
            else:
                self.hdb._config['stimulus_residual_memory_promotion_enabled'] = old_promotion_enabled
            if old_skip_enabled is None:
                self.hdb._config.pop('stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled', None)
            else:
                self.hdb._config['stimulus_residual_memory_shadow_skip_when_promotion_disabled_enabled'] = old_skip_enabled

    def test_owner_runtime_candidate_view_uses_recent_strong_and_explore_budgets(self):
        entries = []
        for index in range(10):
            entries.append(
                {
                    'entry_id': f'e_{index:02d}',
                    'base_weight': float(index + 1),
                    'recent_gain': 1.0,
                    'fatigue': 0.0,
                    'last_updated_at': 100 + index,
                    'last_matched_at': 100 + index,
                }
            )
        config = {
            'owner_db_runtime_budget_enabled': True,
            'owner_db_runtime_recent_budget': 3,
            'owner_db_runtime_strong_budget': 2,
            'owner_db_runtime_explore_budget': 2,
        }
        selected, debug = build_owner_runtime_candidate_view(
            entries=entries,
            config=config,
            owner_structure_id='st_owner',
            path_kind='unit_test',
            tick_id='tick_1',
        )
        selected_ids = [entry.get('entry_id', '') for entry in selected]
        self.assertEqual(len(selected_ids), 7)
        self.assertEqual(selected_ids[:3], ['e_09', 'e_08', 'e_07'])
        self.assertIn('e_06', selected_ids)
        self.assertIn('e_05', selected_ids)
        self.assertEqual(debug.get('selected_count'), 7)
        self.assertEqual(debug.get('recent_selected_count'), 3)
        self.assertEqual(debug.get('strong_selected_count'), 2)
        self.assertEqual(debug.get('explore_selected_count'), 2)

    def test_owner_runtime_candidate_view_explore_rotates_across_ticks(self):
        entries = []
        for index in range(12):
            entries.append(
                {
                    'entry_id': f'e_{index:02d}',
                    'base_weight': float(index + 1),
                    'recent_gain': 1.0,
                    'fatigue': 0.0,
                    'last_updated_at': 100 + index,
                    'last_matched_at': 100 + index,
                }
            )
        config = {
            'owner_db_runtime_budget_enabled': True,
            'owner_db_runtime_recent_budget': 2,
            'owner_db_runtime_strong_budget': 2,
            'owner_db_runtime_explore_budget': 3,
        }
        selected_a, debug_a = build_owner_runtime_candidate_view(
            entries=entries,
            config=config,
            owner_structure_id='st_owner',
            path_kind='unit_test',
            tick_id='tick_1',
        )
        selected_b, debug_b = build_owner_runtime_candidate_view(
            entries=entries,
            config=config,
            owner_structure_id='st_owner',
            path_kind='unit_test',
            tick_id='tick_2',
        )
        head_ids = {'e_11', 'e_10', 'e_09', 'e_08'}
        explore_a = [entry.get('entry_id', '') for entry in selected_a if entry.get('entry_id', '') not in head_ids]
        explore_b = [entry.get('entry_id', '') for entry in selected_b if entry.get('entry_id', '') not in head_ids]
        self.assertEqual(debug_a.get('explore_selected_count'), 3)
        self.assertEqual(debug_b.get('explore_selected_count'), 3)
        self.assertEqual(len(explore_a), 3)
        self.assertEqual(len(explore_b), 3)
        self.assertNotEqual(explore_a, explore_b)

    def test_apply_structure_db_soft_limits_keeps_full_table_when_persistence_trim_disabled(self):
        maintenance = self.hdb._maintenance
        structure_db = {
            'owner_structure_id': 'st_owner',
            'structure_db_id': 'sdb_owner',
            'diff_table': [
                {
                    'entry_id': f'e_{index:03d}',
                    'entry_type': 'structure_ref',
                    'target_id': f'st_target_{index:03d}',
                    'content_signature': f'S:{index:03d}',
                    'base_weight': float(index + 1),
                    'recent_gain': 1.0,
                    'fatigue': 0.0,
                    'last_updated_at': index,
                    'ext': {'relation_type': 'incoming_extension'},
                }
                for index in range(140)
            ],
            'group_table': [
                {'entry_id': f'g_{index:03d}', 'base_weight': 1.0, 'recent_gain': 1.0, 'fatigue': 0.0}
                for index in range(140)
            ],
        }
        out = maintenance.apply_structure_db_soft_limits(structure_db)
        self.assertEqual(len(out.get('diff_table', [])), 140)
        self.assertEqual(len(out.get('group_table', [])), 140)

    def test_collect_local_child_candidates_reports_owner_runtime_budget_metrics(self):
        engine = self.hdb._stimulus
        old_runtime_budget = self.hdb._config.get('owner_db_runtime_budget_enabled')
        old_recent_budget = self.hdb._config.get('owner_db_runtime_recent_budget')
        old_strong_budget = self.hdb._config.get('owner_db_runtime_strong_budget')
        old_explore_budget = self.hdb._config.get('owner_db_runtime_explore_budget')
        self.hdb._config['owner_db_runtime_budget_enabled'] = True
        self.hdb._config['owner_db_runtime_recent_budget'] = 2
        self.hdb._config['owner_db_runtime_strong_budget'] = 1
        self.hdb._config['owner_db_runtime_explore_budget'] = 1
        try:
            owner_db = {
                'owner_structure_id': 'st_owner',
                'structure_db_id': 'sdb_owner',
                'diff_table': [],
            }
            for index in range(8):
                target_id = f'st_target_{index:02d}'
                self.hdb._structure_store._structures[target_id] = {
                    'id': target_id,
                    'structure': {'display_text': target_id, 'content_signature': f'S:{index:02d}', 'sequence_groups': []},
                    'db_pointer': {},
                }
                owner_db['diff_table'].append(
                    {
                        'entry_id': f'e_{index:02d}',
                        'entry_type': 'structure_ref',
                        'target_id': target_id,
                        'content_signature': f'S:{index:02d}',
                        'base_weight': float(index + 1),
                        'recent_gain': 1.0,
                        'fatigue': 0.0,
                        'last_updated_at': 100 + index,
                        'last_matched_at': 100 + index,
                        'ext': {'relation_type': 'incoming_extension'},
                    }
                )
            self.hdb._structure_store._structure_dbs['sdb_owner'] = owner_db
            self.hdb._structure_store._owner_to_db['st_owner'] = 'sdb_owner'
            engine._runtime_cache = {'metrics': {}}
            result = engine._collect_local_child_candidates(
                owner_match={'structure_id': 'st_owner'},
                structure_store=self.hdb._structure_store,
            )
            metrics = engine._runtime_cache.get('metrics', {})
            self.assertEqual(metrics.get('owner_runtime_budget_selected_count'), 4)
            self.assertEqual(metrics.get('owner_runtime_budget_pruned_count'), 4)
            self.assertEqual(len(result.get('candidates', [])), 4)
        finally:
            engine._runtime_cache = None
            if old_runtime_budget is None:
                self.hdb._config.pop('owner_db_runtime_budget_enabled', None)
            else:
                self.hdb._config['owner_db_runtime_budget_enabled'] = old_runtime_budget
            if old_recent_budget is None:
                self.hdb._config.pop('owner_db_runtime_recent_budget', None)
            else:
                self.hdb._config['owner_db_runtime_recent_budget'] = old_recent_budget
            if old_strong_budget is None:
                self.hdb._config.pop('owner_db_runtime_strong_budget', None)
            else:
                self.hdb._config['owner_db_runtime_strong_budget'] = old_strong_budget
            if old_explore_budget is None:
                self.hdb._config.pop('owner_db_runtime_explore_budget', None)
            else:
                self.hdb._config['owner_db_runtime_explore_budget'] = old_explore_budget

    def test_stimulus_common_structure_requires_owner_containment_and_temporal_alignment(self):
        seed_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._grouped_packet(['A', 'B'], packet_id='stimulus_owner_guard_seed_pkt'),
            trace_id='stimulus_owner_guard_seed',
            max_rounds=6,
        )
        self.assertTrue(seed_result['success'])

        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._grouped_packet(['B', 'A', 'C'], packet_id='stimulus_owner_guard_current_pkt'),
            trace_id='stimulus_owner_guard_current',
            max_rounds=6,
        )
        self.assertTrue(result['success'])
        self.assertFalse(any(detail.get('created_common_structure') for detail in result['data']['debug']['round_details']))

        atomic_a = self._find_structure_by_flat_tokens(['A'])
        self.assertIsNotNone(atomic_a)
        _, owner_common_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='structure_ref',
            relation_type='residual_context_common',
        )
        self.assertEqual(len(owner_common_entries), 0)

        _, owner_raw_entries = self._owner_db_entries(
            atomic_a['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertGreaterEqual(len(owner_raw_entries), 2)

    def test_grouped_numeric_residuals_reuse_one_canonical_structure_and_keep_all_group_attributes(self):
        packet = self._grouped_numeric_packet(
            [('你好', 1.1), ('呀', 1.1), ('!', 0.4235)],
            packet_id='grouped_numeric_pkt',
        )
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=packet,
            trace_id='grouped_numeric_trace',
            max_rounds=6,
        )
        self.assertTrue(result['success'])
        self.assertFalse(any(detail.get('created_common_structure') for detail in result['data']['debug']['round_details']))

        atomic_nihao = self._find_structure_by_flat_tokens(['你好'])
        atomic_ya = self._find_structure_by_flat_tokens(['呀'])
        atomic_intensity = self._find_structure_by_flat_tokens(['stimulus_intensity:1.1'])
        self.assertIsNotNone(atomic_nihao)
        self.assertIsNotNone(atomic_ya)
        self.assertIsNotNone(atomic_intensity)

        _, nihao_entries = self._owner_db_entries(
            atomic_nihao['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        _, ya_entries = self._owner_db_entries(
            atomic_ya['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        _, intensity_entries = self._owner_db_entries(
            atomic_intensity['id'],
            entry_type='raw_residual',
            relation_type='stimulus_raw_residual',
        )
        self.assertEqual(len(nihao_entries), 1)
        self.assertEqual(len(ya_entries), 1)
        self.assertEqual(len(intensity_entries), 1)
        self.assertEqual(nihao_entries[0]['canonical_content_signature'], ya_entries[0]['canonical_content_signature'])
        self.assertEqual(nihao_entries[0]['canonical_content_signature'], intensity_entries[0]['canonical_content_signature'])
        self.assertEqual(nihao_entries[0]['canonical_display_text'], ya_entries[0]['canonical_display_text'])

        restored_profile = {'sequence_groups': list(nihao_entries[0].get('canonical_sequence_groups', []))}
        self.assertEqual(len(restored_profile.get('sequence_groups', [])), 3)
        group_token_sets = [
            {str(unit.get('token', '')) for unit in group.get('units', []) if str(unit.get('token', ''))}
            for group in restored_profile.get('sequence_groups', [])
        ]
        self.assertIn({'你好', 'stimulus_intensity:1.1'}, group_token_sets)
        self.assertIn({'呀', 'stimulus_intensity:1.1'}, group_token_sets)
        self.assertIn({'!', 'stimulus_intensity:0.4235'}, group_token_sets)

    def test_grouped_stimulus_overlap_keeps_temporal_groups_and_full_residual_memory(self):
        seed_packet = self._packet_from_group_specs(
            [
                {'features': ['你好'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'current'},
                {'features': ['呀'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'current'},
                {'features': ['!'], 'attr_name': 'stimulus_intensity', 'attr_value': 0.4235, 'feature_er': 0.4235, 'source_type': 'current'},
            ],
            packet_id='seed_grouped_pkt',
        )
        seed_result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=seed_packet,
            trace_id='seed_grouped_trace',
            max_rounds=6,
        )
        self.assertTrue(seed_result['success'])

        current_packet = self._packet_from_group_specs(
            [
                {'features': ['你好'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'echo'},
                {'features': ['呀'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'echo'},
                {'features': ['!'], 'feature_er': 0.44, 'source_type': 'echo'},
                {'features': ['你'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'current'},
                {'features': ['也好'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'current'},
                {'features': ['呀'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'current'},
                {'features': ['!'], 'attr_name': 'stimulus_intensity', 'attr_value': 0.4235, 'feature_er': 0.4235, 'source_type': 'current'},
                {'features': ['你好', '呀'], 'attr_name': 'stimulus_intensity', 'attr_value': 1.1, 'source_type': 'internal'},
            ],
            packet_id='current_grouped_pkt',
        )
        result = self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=current_packet,
            trace_id='current_grouped_trace',
            max_rounds=10,
        )
        self.assertTrue(result['success'])

        expected_common = '{(你好 + stimulus_intensity:1.1)} / {(呀 + stimulus_intensity:1.1)} / {!}'
        expected_residual = (
            '{(你好 + stimulus_intensity:1.1)} / {(呀 + stimulus_intensity:1.1)} / {!} / '
            '{(你 + stimulus_intensity:1.1)} / {(也好 + stimulus_intensity:1.1)} / {(呀 + stimulus_intensity:1.1)} / '
            '{(! + stimulus_intensity:0.4235)} / {(你好 + 呀 + stimulus_intensity:1.1)}'
        )

        matching_rounds = [
            round_detail
            for round_detail in result['data']['debug']['round_details']
            if (round_detail.get('created_common_structure') or {}).get('grouped_display_text') == expected_common
            and (round_detail.get('created_residual_structure') or {}).get('canonical_grouped_display_text') == expected_residual
        ]
        self.assertTrue(matching_rounds)
        self.assertTrue(
            all(
                'SELF[' in (round_detail.get('created_residual_structure') or {}).get('raw_grouped_display_text', '')
                for round_detail in matching_rounds
            )
        )


if __name__ == '__main__':
    unittest.main()
