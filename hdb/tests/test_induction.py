# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB
from hdb._context_metadata import extract_context_metadata
from hdb._structure_resolver import resolve_or_create_structure_from_profile


class TestHDBInduction(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_induction_')
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _packet(self, text: str) -> dict:
        sa_items = []
        for idx, ch in enumerate(text):
            sa_items.append({
                'id': f'sa_in_{text}_{idx}',
                'object_type': 'sa',
                'content': {'raw': ch, 'display': ch, 'normalized': ch},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': idx}},
            })
        return {
            'id': f'spkt_in_{text}',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_in', 'sa_ids': [item['id'] for item in sa_items], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def _packet_from_groups(self, groups: list[str]) -> dict:
        sa_items = []
        grouped_sa_sequences = []
        flat_index = 0
        for group_index, text in enumerate(groups):
            sa_ids = []
            for inner_index, ch in enumerate(text):
                sa_id = f"sa_grp_{group_index}_{flat_index}"
                sa_items.append({
                    'id': sa_id,
                    'object_type': 'sa',
                    'content': {'raw': ch, 'display': ch, 'normalized': ch},
                    'stimulus': {'role': 'feature', 'modality': 'text'},
                    'energy': {'er': 1.0, 'ev': 0.0},
                    'ext': {'packet_context': {'sequence_index': flat_index, 'group_index': group_index, 'group_inner_index': inner_index}},
                })
                sa_ids.append(sa_id)
                flat_index += 1
            grouped_sa_sequences.append(
                {
                    'group_index': group_index,
                    'source_type': 'current',
                    'origin_frame_id': f'frame_grp_{group_index}',
                    'sa_ids': sa_ids,
                    'csa_ids': [],
                }
            )
        packet_id = "_".join(groups)
        return {
            'id': f'spkt_grp_{packet_id}',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': grouped_sa_sequences,
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
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

    def test_induction_generates_targets_from_local_diff_table(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好呀'), trace_id='in_seed_1')
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好！'), trace_id='in_seed_2')

        source_id = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            structure_db = self.hdb._structure_store.get_db_by_owner(structure_obj['id'])
            if structure_db and structure_db.get('diff_table'):
                source_id = structure_obj['id']
                break
        self.assertIsNotNone(source_id)

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_1',
                    'ref_object_type': 'st',
                    'ref_object_id': source_id,
                    'display': source_id,
                    'er': 2.0,
                    'ev': 0.8,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(state_snapshot=state_snapshot, trace_id='in_run', max_source_items=1)
        self.assertTrue(result['success'])
        self.assertGreater(result['data']['total_delta_ev'], 0.0)
        self.assertTrue(result['data']['induced_target_count'] > 0 or result['data']['propagated_target_count'] > 0)
        self.assertTrue(result['data']['induction_targets'])
        # EV propagation consumes only a fraction of source EV (ev_propagation_ratio).
        ev_ratio = float(self.hdb._config.get('ev_propagation_ratio', 0.28))
        self.assertAlmostEqual(result['data']['total_ev_consumed'], 0.8 * ev_ratio, places=6)
        self.assertEqual(len(result['data']['source_ev_consumptions']), 1)
        self.assertAlmostEqual(result['data']['source_ev_consumptions'][0]['consumed_ev'], 0.8 * ev_ratio, places=6)

    def test_atomic_preseed_uses_context_free_identity_by_default(self):
        packet = self._packet('问')
        packet['id'] = 'spkt_atomic_ctx_free'
        packet['source'] = {'parent_ids': ['spkt_runtime_parent', 'ispkt_runtime_parent']}
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='atomic_ctx_free_1')
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='atomic_ctx_free_2')

        matches = [
            structure
            for structure in self.hdb._structure_store.iter_structures()
            if structure.get('source', {}).get('origin') == 'stimulus_atomic_preseed'
            and structure.get('structure', {}).get('flat_tokens') == ['问']
        ]
        self.assertEqual(len(matches), 1)
        context = extract_context_metadata(matches[0])
        self.assertEqual(context['context_ref_object_id'], '')
        self.assertEqual(context['context_owner_structure_id'], '')
        self.assertEqual(context['context_path_ids'], [])
        ext = matches[0].get('structure', {}).get('ext', {})
        self.assertTrue(ext.get('identity_context_free'))
        self.assertEqual(ext.get('provenance_parent_ids'), ['spkt_runtime_parent', 'ispkt_runtime_parent'])

    def test_atomic_preseed_legacy_packet_context_is_switchable(self):
        legacy_temp_dir = tempfile.mkdtemp(prefix='hdb_atomic_legacy_')
        hdb = HDB(
            config_override={
                'data_dir': legacy_temp_dir,
                'enable_background_repair': False,
                'stimulus_atomic_preseed_context_free_identity_enabled': False,
            }
        )
        try:
            packet = self._packet('问')
            packet['id'] = 'spkt_atomic_legacy'
            packet['source'] = {'parent_ids': ['spkt_runtime_parent', 'ispkt_runtime_parent']}
            hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='atomic_legacy_1')
            matches = [
                structure
                for structure in hdb._structure_store.iter_structures()
                if structure.get('source', {}).get('origin') == 'stimulus_atomic_preseed'
                and structure.get('structure', {}).get('flat_tokens') == ['问']
            ]
            self.assertEqual(len(matches), 1)
            context = extract_context_metadata(matches[0])
            self.assertEqual(context['context_ref_object_id'], 'spkt_runtime_parent')
            self.assertEqual(context['context_path_ids'], ['spkt_runtime_parent', 'ispkt_runtime_parent'])
            self.assertFalse(matches[0].get('structure', {}).get('ext', {}).get('identity_context_free'))
        finally:
            hdb.close()
            shutil.rmtree(legacy_temp_dir, ignore_errors=True)

    def test_goal_b_string_seed_uses_context_free_identity_by_default(self):
        self.hdb._config['enable_goal_b_char_sa_string_mode'] = True
        self.hdb._stimulus.update_config(self.hdb._config)
        packet = self._packet('你好')
        packet['id'] = 'spkt_goal_b_ctx_free'
        packet['grouped_sa_sequences'][0]['order_sensitive'] = True
        packet['grouped_sa_sequences'][0]['string_unit_kind'] = 'char_sequence'
        packet['grouped_sa_sequences'][0]['string_token_text'] = '你好'
        packet['source'] = {'parent_ids': ['spkt_runtime_parent', 'ispkt_runtime_parent']}

        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='goal_b_ctx_free_1')
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='goal_b_ctx_free_2')

        matches = [
            structure
            for structure in self.hdb._structure_store.iter_structures()
            if structure.get('source', {}).get('origin') == 'stimulus_goal_b_string_seed'
            and structure.get('structure', {}).get('flat_tokens') == ['你', '好']
        ]
        self.assertEqual(len(matches), 1)
        context = extract_context_metadata(matches[0])
        self.assertEqual(context['context_ref_object_id'], '')
        self.assertEqual(context['context_owner_structure_id'], '')
        self.assertEqual(context['context_path_ids'], [])
        ext = matches[0].get('structure', {}).get('ext', {})
        self.assertTrue(ext.get('identity_context_free'))
        self.assertEqual(ext.get('provenance_parent_ids'), ['spkt_runtime_parent', 'ispkt_runtime_parent'])

    def test_goal_b_string_seed_legacy_packet_context_is_switchable(self):
        legacy_temp_dir = tempfile.mkdtemp(prefix='hdb_goal_b_legacy_')
        hdb = HDB(
            config_override={
                'data_dir': legacy_temp_dir,
                'enable_background_repair': False,
                'enable_goal_b_char_sa_string_mode': True,
                'stimulus_goal_b_string_seed_context_free_identity_enabled': False,
            }
        )
        try:
            packet = self._packet('你好')
            packet['id'] = 'spkt_goal_b_legacy'
            packet['grouped_sa_sequences'][0]['order_sensitive'] = True
            packet['grouped_sa_sequences'][0]['string_unit_kind'] = 'char_sequence'
            packet['grouped_sa_sequences'][0]['string_token_text'] = '你好'
            packet['source'] = {'parent_ids': ['spkt_runtime_parent', 'ispkt_runtime_parent']}
            hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='goal_b_legacy_1')
            matches = [
                structure
                for structure in hdb._structure_store.iter_structures()
                if structure.get('source', {}).get('origin') == 'stimulus_goal_b_string_seed'
                and structure.get('structure', {}).get('flat_tokens') == ['你', '好']
            ]
            self.assertEqual(len(matches), 1)
            context = extract_context_metadata(matches[0])
            self.assertEqual(context['context_ref_object_id'], 'spkt_runtime_parent')
            self.assertEqual(context['context_path_ids'], ['spkt_runtime_parent', 'ispkt_runtime_parent'])
            self.assertFalse(matches[0].get('structure', {}).get('ext', {}).get('identity_context_free'))
        finally:
            hdb.close()
            shutil.rmtree(legacy_temp_dir, ignore_errors=True)

    def test_shared_resolver_context_free_ignores_parent_ids_as_identity(self):
        profile = self.hdb._cut.build_sequence_profile_from_stimulus_packet(self._packet('问'))
        result = resolve_or_create_structure_from_profile(
            profile={
                **dict(profile),
                'ext': {
                    **dict(profile.get('ext', {}) or {}),
                    'owner_structure_id': 'st_owner_demo',
                    'context_ref_object_id': 'st_owner_demo',
                    'context_owner_structure_id': 'st_owner_demo',
                },
            },
            structure_store=self.hdb._structure_store,
            pointer_index=self.hdb._pointer_index,
            cut_engine=self.hdb._cut,
            trace_id='resolver_ctx_free_parent_guard',
            tick_id='resolver_ctx_free_parent_guard',
            confidence=0.8,
            origin='resolver_ctx_free_parent_guard',
            origin_id='spkt_ctx_free_parent_guard',
            parent_ids=['spkt_runtime_parent', 'st_owner_demo'],
            ext={'owner_structure_id': 'st_owner_demo'},
            source_interface='test_shared_resolver_context_free',
            require_context_free=True,
        )
        structure = result.get('structure')
        self.assertIsNotNone(structure)
        context = extract_context_metadata(structure)
        self.assertEqual(context['context_ref_object_id'], '')
        self.assertEqual(context['context_owner_structure_id'], '')
        self.assertEqual(context['context_path_ids'], [])
        self.assertEqual(structure.get('source', {}).get('parent_ids', []), [])
        ext = structure.get('structure', {}).get('ext', {})
        self.assertEqual(ext.get('provenance_owner_structure_id'), 'st_owner_demo')
        self.assertEqual(ext.get('provenance_parent_ids'), ['spkt_runtime_parent', 'st_owner_demo'])

    def test_induction_accepts_sa_and_em_runtime_sources(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('A'), trace_id='runtime_src_seed_a')
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('AB'), trace_id='runtime_src_seed_ab')

        source_id = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            flat_tokens = list(structure_obj.get('structure', {}).get('flat_tokens', []))
            structure_db = self.hdb._structure_store.get_db_by_owner(structure_obj['id'])
            if flat_tokens == ['A'] and structure_db and structure_db.get('diff_table'):
                source_id = structure_obj['id']
                break
        self.assertIsNotNone(source_id)

        state_snapshot = {
            'summary': {'active_item_count': 2},
            'top_items': [
                {
                    'id': 'runtime_source_sa',
                    'ref_object_type': 'sa',
                    'ref_object_id': 'sa_runtime_a',
                    'display': 'A',
                    'display_text': 'A',
                    'er': 1.2,
                    'ev': 0.4,
                    'ref_snapshot': {
                        'content_display': 'A',
                        'flat_tokens': ['A'],
                    },
                },
                {
                    'id': 'runtime_source_em',
                    'ref_object_type': 'em',
                    'ref_object_id': 'em_runtime_a',
                    'display': 'A',
                    'display_text': 'A',
                    'er': 0.8,
                    'ev': 0.7,
                    'ref_snapshot': {
                        'content_display': 'A',
                        'sequence_groups': [
                            {
                                'group_index': 0,
                                'source_type': 'memory',
                                'origin_frame_id': 'em_runtime_a',
                                'tokens': ['A'],
                            }
                        ],
                        'structure_refs': [source_id],
                        'backing_structure_id': source_id,
                    },
                },
            ],
        }

        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='runtime_src_induction',
            max_source_items=None,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(result['success'])
        data = result['data']
        self.assertEqual(data.get('source_item_count', 0), 2)
        self.assertTrue(data.get('induction_targets'))
        self.assertGreater(data.get('total_delta_ev', 0.0), 0.0)

        details = list((data.get('debug', {}) or {}).get('source_details', []) or [])
        self.assertEqual(len(details), 2)
        by_type = {str(item.get('source_ref_object_type', '') or ''): item for item in details}
        self.assertIn('sa', by_type)
        self.assertIn('em', by_type)
        self.assertIn(source_id, list(by_type['sa'].get('resolved_support_structure_ids', []) or []))
        self.assertIn(source_id, list(by_type['em'].get('resolved_support_structure_ids', []) or []))
        self.assertNotIn('skipped_reason', by_type['sa'])
        self.assertNotIn('skipped_reason', by_type['em'])

    def test_projected_sa_context_owner_does_not_open_owner_db_without_explicit_support(self):
        structure_a = self._store_packet_as_structure(self._packet('A'), trace_id='ctx_owner_seed_a')
        structure_ab = self._store_packet_as_structure(self._packet('AB'), trace_id='ctx_owner_seed_ab')
        self.hdb._structure_store.add_diff_entry(
            structure_a['id'],
            target_id=structure_ab['id'],
            content_signature=structure_ab.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='b',
            ext={'relation_type': 'incoming_extension'},
        )

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_projected_sa_no_backing',
                    'ref_object_type': 'sa',
                    'ref_object_id': 'sa_projected_z',
                    'display': 'Z',
                    'display_text': 'Z',
                    'er': 0.0,
                    'ev': 1.0,
                    'context_owner_id': structure_a['id'],
                    'context_ref_object_id': structure_a['id'],
                    'context_ref_object_type': 'st',
                    'ref_snapshot': {
                        'content_display': 'Z',
                        'flat_tokens': ['Z'],
                        'context_owner_id': structure_a['id'],
                        'context_ref_object_id': structure_a['id'],
                        'context_ref_object_type': 'st',
                    },
                }
            ],
        }

        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='ctx_owner_no_backing_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )

        self.assertTrue(result['success'])
        data = result['data']
        self.assertEqual(data.get('total_delta_ev', 0.0), 0.0)
        self.assertFalse(data.get('induction_targets'))

    def test_runtime_source_structure_lookup_cache_reuses_empty_result_until_structure_revision_changes(self):
        source_item = {
            'id': 'runtime_action_focus',
            'item_id': 'runtime_action_focus',
            'ref_object_type': 'sa',
            'ref_object_id': 'sa_runtime_ab',
            'display_text': 'AB',
            'display': 'AB',
            'er': 0.0,
            'ev': 1.0,
            'ref_snapshot': {
                'content_display': 'AB',
                'flat_tokens': ['A', 'B'],
            },
        }
        engine = self.hdb._induction
        cut_engine = self.hdb._cut
        structure_store = self.hdb._structure_store
        pointer_index = self.hdb._pointer_index

        profile = engine._build_runtime_source_profile(
            source_item=source_item,
            source_structure_obj=None,
            cut_engine=cut_engine,
        )
        self.assertTrue(profile)

        engine._runtime_cache = {'runtime_source_structure_lookup': {}}
        engine._current_structure_store = structure_store
        try:
            cache = engine._runtime_cache['runtime_source_structure_lookup']
            self.assertEqual(len(cache), 0)

            resolved_before = engine._resolve_runtime_source_structure_by_profile(
                source_item=source_item,
                source_profile=profile,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
            )
            self.assertEqual(resolved_before, '')
            self.assertEqual(len(cache), 1)

            structure_obj = self._store_packet_as_structure(self._packet('AB'), trace_id='runtime_lookup_cache_seed')
            self.assertIsNotNone(structure_obj)

            resolved_after = engine._resolve_runtime_source_structure_by_profile(
                source_item=source_item,
                source_profile=profile,
                structure_store=structure_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
            )
            self.assertEqual(resolved_after, structure_obj['id'])
            self.assertEqual(len(cache), 2)
        finally:
            engine._runtime_cache = None
            engine._current_structure_store = None

    def test_runtime_source_template_cache_for_empty_support_rebuilds_after_structure_lookup_revision_changes(self):
        source_item = {
            'id': 'runtime_source_template_probe',
            'item_id': 'runtime_source_template_probe',
            'ref_object_type': 'sa',
            'ref_object_id': 'sa_runtime_ab',
            'display_text': 'AB',
            'display': 'AB',
            'er': 0.0,
            'ev': 1.0,
            'ref_snapshot': {
                'content_display': 'AB',
                'flat_tokens': ['A', 'B'],
            },
        }
        engine = self.hdb._induction
        cut_engine = self.hdb._cut
        structure_store = self.hdb._structure_store
        pointer_index = self.hdb._pointer_index
        episodic_store = self.hdb._episodic_store

        engine._runtime_cache = {
            'runtime_source_profiles': {},
            'runtime_source_data_templates': {},
            'runtime_source_structure_lookup': {},
            'structure_profiles': {},
            'entry_profiles': {},
        }
        engine._current_structure_store = structure_store
        try:
            first = engine._resolve_runtime_source_data(
                source_item=source_item,
                structure_store=structure_store,
                episodic_store=episodic_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                now_ms=0,
                trace_id='runtime_template_probe_1',
                tick_id='runtime_template_probe_1',
                structure_source_cache={},
            )
            self.assertEqual(list(first.get('support_structure_ids', []) or []), [])
            self.assertEqual(list(first.get('resolved_support_structure_ids', []) or []), [])

            structure_obj = self._store_packet_as_structure(self._packet('AB'), trace_id='runtime_template_probe_seed')
            self.assertIsNotNone(structure_obj)

            second = engine._resolve_runtime_source_data(
                source_item=source_item,
                structure_store=structure_store,
                episodic_store=episodic_store,
                pointer_index=pointer_index,
                cut_engine=cut_engine,
                now_ms=0,
                trace_id='runtime_template_probe_2',
                tick_id='runtime_template_probe_2',
                structure_source_cache={},
            )
            self.assertIn(structure_obj['id'], list(second.get('support_structure_ids', []) or []))
            self.assertIn(structure_obj['id'], list(second.get('resolved_support_structure_ids', []) or []))
        finally:
            engine._runtime_cache = None
            engine._current_structure_store = None

    def test_projected_sa_explicit_backing_structure_still_opens_owner_db(self):
        structure_a = self._store_packet_as_structure(self._packet('A'), trace_id='explicit_backing_seed_a')
        structure_ab = self._store_packet_as_structure(self._packet('AB'), trace_id='explicit_backing_seed_ab')
        self.hdb._structure_store.add_diff_entry(
            structure_a['id'],
            target_id=structure_ab['id'],
            content_signature=structure_ab.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='b',
            ext={'relation_type': 'incoming_extension'},
        )

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_projected_sa_with_backing',
                    'ref_object_type': 'sa',
                    'ref_object_id': 'sa_projected_z',
                    'display': 'Z',
                    'display_text': 'Z',
                    'er': 0.0,
                    'ev': 1.0,
                    'backing_structure_id': structure_a['id'],
                    'context_owner_id': structure_a['id'],
                    'context_ref_object_id': structure_a['id'],
                    'context_ref_object_type': 'st',
                    'ref_snapshot': {
                        'content_display': 'Z',
                        'flat_tokens': ['Z'],
                        'backing_structure_id': structure_a['id'],
                        'context_owner_id': structure_a['id'],
                        'context_ref_object_id': structure_a['id'],
                        'context_ref_object_type': 'st',
                    },
                }
            ],
        }

        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='explicit_backing_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )

        self.assertTrue(result['success'])
        data = result['data']
        self.assertGreater(data.get('total_delta_ev', 0.0), 0.0)
        self.assertTrue(
            any(
                item.get('target_structure_id') == structure_ab['id']
                for item in data.get('induction_targets', [])
            )
        )
        details = list((data.get('debug', {}) or {}).get('source_details', []) or [])
        self.assertEqual(len(details), 1)
        self.assertIn(structure_a['id'], list(details[0].get('support_structure_ids', []) or []))
        self.assertIn(structure_a['id'], list(details[0].get('resolved_support_structure_ids', []) or []))

    def test_induction_aggregates_duplicate_target_paths_by_unique_structure(self):
        self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('A'), trace_id='dup_seed_a')
        structure_ab = self._store_packet_as_structure(self._packet('AB'), trace_id='dup_seed_ab')
        structure_ac = self._store_packet_as_structure(self._packet('AC'), trace_id='dup_seed_ac')

        atomic_a = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            flat_tokens = list(structure_obj.get('structure', {}).get('flat_tokens', []))
            if flat_tokens == ['A']:
                atomic_a = structure_obj
        self.assertIsNotNone(atomic_a)
        self.assertIsNotNone(structure_ab)
        self.assertIsNotNone(structure_ac)

        self.hdb._structure_store.add_diff_entry(
            atomic_a['id'],
            target_id=structure_ab['id'],
            content_signature=structure_ab.get('structure', {}).get('content_signature', ''),
            base_weight=0.55,
            residual_existing_signature='',
            residual_incoming_signature='shadow',
            ext={'relation_type': 'incoming_extension'},
        )
        self.hdb._structure_store.add_diff_entry(
            atomic_a['id'],
            target_id=structure_ac['id'],
            content_signature=structure_ac.get('structure', {}).get('content_signature', ''),
            base_weight=0.65,
            residual_existing_signature='',
            residual_incoming_signature='tail',
            ext={'relation_type': 'incoming_extension'},
        )

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_dup',
                    'ref_object_type': 'st',
                    'ref_object_id': atomic_a['id'],
                    'display': 'A',
                    'er': 0.6,
                    'ev': 0.9,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(state_snapshot=state_snapshot, trace_id='dup_induction', max_source_items=1)
        self.assertTrue(result['success'])

        ev_targets = [item for item in result['data']['induction_targets'] if item.get('modes') == ['ev_propagation']]
        self.assertEqual(
            len([item for item in ev_targets if item.get('target_structure_id') == structure_ab['id']]),
            1,
        )
        self.assertEqual(
            len([item for item in ev_targets if item.get('target_structure_id') == structure_ac['id']]),
            1,
        )
        # EV propagation uses ev_propagation_ratio fraction of source EV.
        ev_ratio = float(self.hdb._config.get('ev_propagation_ratio', 0.28))
        self.assertAlmostEqual(sum(item.get('delta_ev', 0.0) for item in ev_targets), 0.9 * ev_ratio, places=6)

    def test_induction_keeps_residual_context_common_even_when_target_is_not_full_inclusion(self):
        structure_a = self._store_packet_as_structure(self._packet('A'), trace_id='common_ctx_seed_a')
        structure_b = self._store_packet_as_structure(self._packet('B'), trace_id='common_ctx_seed_b')
        self.hdb._structure_store.add_diff_entry(
            structure_a['id'],
            target_id=structure_b['id'],
            content_signature=structure_b.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='b',
            ext={
                'relation_type': 'residual_context_common',
                'owner_structure_id': structure_a['id'],
            },
        )

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_common_ctx',
                    'ref_object_type': 'st',
                    'ref_object_id': structure_a['id'],
                    'display': 'A',
                    'er': 1.0,
                    'ev': 0.8,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='common_ctx_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(result['success'])
        data = result['data']
        self.assertTrue(any(item.get('target_structure_id') == structure_b['id'] for item in data.get('induction_targets', [])))
        details = list((data.get('debug', {}) or {}).get('source_details', []) or [])
        self.assertEqual(len(details), 1)
        self.assertTrue(
            any(
                item.get('target_structure_id') == structure_b['id']
                and item.get('relation_type') == 'residual_context_common'
                for item in details[0].get('candidate_entries', [])
            )
        )

    def test_induction_includes_owner_raw_residual_memory(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='residual_owner_seed',
            max_rounds=1,
        )

        atomic_a = None
        residual_target_id = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == ['A']:
                atomic_a = structure_obj
                break
        self.assertIsNotNone(atomic_a)

        owner_db = self.hdb._structure_store.get_db_by_owner(atomic_a['id'])
        self.assertIsNotNone(owner_db)
        residual_entries = [
            entry for entry in owner_db.get('diff_table', [])
            if entry.get('entry_type') == 'raw_residual'
            and entry.get('ext', {}).get('relation_type') == 'stimulus_raw_residual'
        ]
        self.assertEqual(len(residual_entries), 1)
        residual_memory_id = (residual_entries[0].get('memory_refs', []) or [''])[-1]
        self.assertTrue(residual_memory_id.startswith('em_'))

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_residual_owner',
                    'ref_object_type': 'st',
                    'ref_object_id': atomic_a['id'],
                    'display': 'A',
                    'er': 1.2,
                    'ev': 0.9,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='residual_owner_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(result['success'])
        structure_targets = [
            item for item in result['data']['induction_targets']
            if item.get('target_structure_id')
        ]
        memory_targets = [
            item for item in result['data']['induction_targets']
            if item.get('memory_id') == residual_memory_id
        ]
        self.assertTrue(structure_targets)
        self.assertFalse(memory_targets)
        self.assertIn('er_induction', {tuple(item.get('modes', []))[0] for item in structure_targets})
        self.assertIn('ev_propagation', {tuple(item.get('modes', []))[0] for item in structure_targets})
        self.assertTrue(all(item.get('source_em_id') == residual_memory_id for item in structure_targets))
        self.assertTrue(all(residual_memory_id in list(item.get('raw_residual_memory_refs', []) or []) for item in structure_targets))
        target_structure = self.hdb._structure_store.get(structure_targets[0].get('target_structure_id', ''))
        self.assertIsNotNone(target_structure)
        context = extract_context_metadata(target_structure)
        self.assertEqual(context['context_ref_object_id'], '')
        self.assertEqual(context['context_owner_structure_id'], '')
        self.assertEqual(context['context_path_ids'], [])
        self.assertEqual(list(target_structure.get('structure', {}).get('flat_tokens', [])), ['B'])

    def test_induction_raw_residual_static_cache_reuses_shape_not_runtime_weight(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='residual_static_cache_seed',
            max_rounds=1,
        )

        atomic_a = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            if list(structure_obj.get('structure', {}).get('flat_tokens', [])) == ['A']:
                atomic_a = structure_obj
                break
        self.assertIsNotNone(atomic_a)

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_residual_static_cache',
                    'ref_object_type': 'st',
                    'ref_object_id': atomic_a['id'],
                    'display': 'A',
                    'er': 1.2,
                    'ev': 0.9,
                }
            ],
        }
        first = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='residual_static_cache_first',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(first['success'])
        first_metrics = first['data'].get('metrics', {})
        self.assertGreaterEqual(
            first_metrics.get('induction_raw_residual_projection_profile_cache_store_count', 0),
            1,
        )

        second = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='residual_static_cache_second',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(second['success'])
        second_metrics = second['data'].get('metrics', {})
        self.assertGreaterEqual(
            second_metrics.get('induction_raw_residual_projection_profile_shared_cache_hit_count', 0)
            + second_metrics.get('induction_raw_residual_projection_profile_local_cache_hit_count', 0),
            1,
        )
        self.assertTrue(second['data']['induction_targets'])
        self.assertGreater(second['data'].get('updated_weight_count', 0), 0)
        self.assertGreater(second['data'].get('total_delta_ev', 0.0), 0.0)

    def test_induction_raw_residual_can_split_to_existing_structure(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='residual_split_seed',
            max_rounds=1,
        )

        full_ab = self._store_packet_as_structure(self._packet('AB'), trace_id='residual_split_full_ab')

        atomic_a = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            flat_tokens = list(structure_obj.get('structure', {}).get('flat_tokens', []))
            if flat_tokens == ['A'] and atomic_a is None:
                atomic_a = structure_obj
        self.assertIsNotNone(atomic_a)
        self.assertIsNotNone(full_ab)

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_residual_split',
                    'ref_object_type': 'st',
                    'ref_object_id': atomic_a['id'],
                    'display': 'A',
                    'er': 1.2,
                    'ev': 0.9,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='residual_split_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(result['success'])
        data = result['data']
        self.assertGreaterEqual(data.get('raw_residual_entry_count', 0), 1)
        self.assertGreaterEqual(data.get('raw_residual_entry_with_existing_structure_count', 0), 1)
        self.assertGreaterEqual(data.get('raw_residual_entry_routed_to_structure_count', 0), 1)
        self.assertGreaterEqual(data.get('raw_residual_existing_structure_target_count', 0), 1)
        self.assertEqual(data.get('raw_residual_entry_materialized_structure_count', 0), 0)
        self.assertEqual(data.get('raw_residual_materialized_structure_target_count', 0), 0)
        owner_db = self.hdb._structure_store.get_db_by_owner(atomic_a['id'])
        self.assertIsNotNone(owner_db)
        residual_entries = [
            entry for entry in owner_db.get('diff_table', [])
            if entry.get('entry_type') == 'raw_residual'
            and entry.get('ext', {}).get('relation_type') == 'stimulus_raw_residual'
        ]
        self.assertEqual(len(residual_entries), 1)
        residual_memory_id = (residual_entries[0].get('memory_refs', []) or [''])[-1]
        self.assertTrue(residual_memory_id.startswith('em_'))

        structure_targets = [
            item for item in data['induction_targets']
            if item.get('target_structure_id')
        ]
        memory_targets = [
            item for item in data['induction_targets']
            if item.get('memory_id', '').startswith('em_')
        ]
        self.assertTrue(structure_targets)
        self.assertFalse(memory_targets)
        target_structure = self.hdb._structure_store.get(structure_targets[0].get('target_structure_id', ''))
        self.assertIsNotNone(target_structure)
        context = extract_context_metadata(target_structure)
        self.assertEqual(context['context_ref_object_id'], '')
        self.assertEqual(context['context_owner_structure_id'], '')
        self.assertEqual(context['context_path_ids'], [])
        self.assertEqual(list(target_structure.get('structure', {}).get('flat_tokens', [])), ['B'])
        self.assertNotEqual(str(structure_targets[0].get('target_structure_id', '') or ''), str(full_ab['id']))
        self.assertGreater(
            sum(float(item.get('raw_residual_structure_delta_ev', 0.0)) for item in structure_targets),
            0.0,
        )
        self.assertAlmostEqual(
            sum(float(item.get('raw_residual_memory_delta_ev', 0.0)) for item in structure_targets),
            0.0,
            places=6,
        )
        self.assertTrue(all(item.get('source_em_id') == residual_memory_id for item in structure_targets))
        self.assertTrue(all(residual_memory_id in list(item.get('raw_residual_memory_refs', []) or []) for item in structure_targets))
        self.assertGreater(data.get('raw_residual_structure_budget_weight', 0.0), 0.0)
        self.assertAlmostEqual(data.get('raw_residual_hit_memory_budget_weight', 0.0), 0.0, places=6)
        self.assertAlmostEqual(data.get('raw_residual_miss_memory_budget_weight', 0.0), 0.0, places=6)

    def test_induction_raw_residual_can_fallback_to_group_component_structures(self):
        owner = self._store_packet_as_structure(self._packet('ROOT'), trace_id='component_owner_seed')
        structure_abc = self._store_packet_as_structure(self._packet('ABC'), trace_id='component_struct_abc')
        structure_def = self._store_packet_as_structure(self._packet('DEF'), trace_id='component_struct_def')
        residual_packet = self._packet_from_groups(['ABC', 'DEF'])
        residual_profile = self.hdb._cut.build_sequence_profile_from_stimulus_packet(residual_packet)
        append_result = self.hdb.append_episodic_memory(
            episodic_payload={
                'event_summary': 'component residual memory',
                'structure_refs': [owner['id']],
                'group_refs': [],
            },
            trace_id='component_memory_seed',
        )
        self.assertTrue(append_result['success'])
        memory_id = append_result['data']['episodic_id']
        entry = self.hdb._structure_store.add_diff_entry(
            owner['id'],
            target_id='',
            content_signature=str(residual_profile.get('content_signature', '')),
            base_weight=0.9,
            entry_type='raw_residual',
            residual_existing_signature='',
            residual_incoming_signature='component_tail',
            ext={
                'relation_type': 'stimulus_raw_residual',
                'canonical_display_text': residual_profile.get('display_text', ''),
                'context_owner_structure_id': owner['id'],
            },
        )
        self.assertIsNotNone(entry)
        entry['display_text'] = residual_profile.get('display_text', '')
        entry['flat_tokens'] = list(residual_profile.get('flat_tokens', []))
        entry['sequence_groups'] = list(residual_profile.get('sequence_groups', []))
        entry['canonical_content_signature'] = residual_profile.get('content_signature', '')
        entry['canonical_display_text'] = residual_profile.get('display_text', '')
        entry['canonical_flat_tokens'] = list(residual_profile.get('flat_tokens', []))
        entry['canonical_sequence_groups'] = list(residual_profile.get('sequence_groups', []))
        entry['memory_refs'] = [memory_id]
        owner_db = self.hdb._structure_store.get_db_by_owner(owner['id'])
        self.assertIsNotNone(owner_db)
        self.hdb._structure_store.update_db(owner_db)

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_component_split',
                    'ref_object_type': 'st',
                    'ref_object_id': owner['id'],
                    'display': 'ROOT',
                    'er': 1.1,
                    'ev': 0.9,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='component_split_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )
        self.assertTrue(result['success'])
        data = result['data']
        self.assertGreaterEqual(data.get('raw_residual_entry_count', 0), 1)
        self.assertEqual(data.get('raw_residual_entry_with_existing_structure_count', 0), 0)
        self.assertGreaterEqual(data.get('raw_residual_entry_materialized_structure_count', 0), 1)
        self.assertGreaterEqual(data.get('raw_residual_materialized_structure_target_count', 0), 1)
        self.assertEqual(data.get('raw_residual_entry_routed_to_component_structure_count', 0), 0)
        self.assertEqual(data.get('raw_residual_component_structure_target_count', 0), 0)
        self.assertAlmostEqual(data.get('raw_residual_component_structure_budget_weight', 0.0), 0.0, places=6)

        structure_targets = [
            item for item in data['induction_targets']
            if item.get('target_structure_id')
        ]
        memory_targets = [
            item for item in data['induction_targets']
            if item.get('memory_id') == memory_id
        ]
        self.assertTrue(structure_targets)
        self.assertFalse(memory_targets)
        target_structure = self.hdb._structure_store.get(structure_targets[0].get('target_structure_id', ''))
        self.assertIsNotNone(target_structure)
        context = extract_context_metadata(target_structure)
        self.assertEqual(context['context_ref_object_id'], '')
        self.assertEqual(context['context_owner_structure_id'], '')
        self.assertEqual(context['context_path_ids'], [])
        self.assertEqual(
            list(target_structure.get('structure', {}).get('flat_tokens', [])),
            ['A', 'B', 'C', 'D', 'E', 'F'],
        )
        self.assertNotIn(
            str(structure_targets[0].get('target_structure_id', '') or ''),
            {str(structure_abc['id']), str(structure_def['id'])},
        )

    def test_induction_raw_residual_materialization_uses_shared_context_free_identity_and_owner_entries(self):
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('AB'),
            trace_id='ctx_seed_ab',
            max_rounds=1,
        )
        self.hdb.run_stimulus_level_retrieval_storage(
            stimulus_packet=self._packet('CB'),
            trace_id='ctx_seed_cb',
            max_rounds=1,
        )

        atomic_a = None
        atomic_c = None
        for structure_obj in self.hdb._structure_store.iter_structures():
            flat_tokens = list(structure_obj.get('structure', {}).get('flat_tokens', []))
            if flat_tokens == ['A'] and atomic_a is None:
                atomic_a = structure_obj
            if flat_tokens == ['C'] and atomic_c is None:
                atomic_c = structure_obj
        self.assertIsNotNone(atomic_a)
        self.assertIsNotNone(atomic_c)

        def _run(owner_id: str, trace_id: str) -> tuple[dict, dict]:
            result = self.hdb.run_induction_propagation(
                state_snapshot={
                    'summary': {'active_item_count': 1},
                    'top_items': [
                        {
                            'id': f'runtime_{trace_id}',
                            'ref_object_type': 'st',
                            'ref_object_id': owner_id,
                            'display': owner_id,
                            'er': 1.0,
                            'ev': 0.8,
                        }
                    ],
                },
                trace_id=trace_id,
                max_source_items=1,
                enable_ev_propagation=True,
                enable_er_induction=True,
            )
            self.assertTrue(result['success'])
            targets = [
                item for item in result['data']['induction_targets']
                if item.get('target_structure_id')
            ]
            self.assertTrue(targets)
            target_structure = self.hdb._structure_store.get(targets[0].get('target_structure_id', ''))
            self.assertIsNotNone(target_structure)
            return targets[0], target_structure

        target_a, structure_a = _run(atomic_a['id'], 'ctx_induction_a')
        target_c, structure_c = _run(atomic_c['id'], 'ctx_induction_c')

        structure_a_id = str(target_a.get('target_structure_id', '') or '')
        structure_c_id = str(target_c.get('target_structure_id', '') or '')
        self.assertTrue(structure_a_id.startswith('st_'))
        self.assertTrue(structure_c_id.startswith('st_'))
        self.assertEqual(structure_a_id, structure_c_id)

        self.assertEqual(list(structure_a.get('structure', {}).get('flat_tokens', [])), ['B'])
        self.assertEqual(list(structure_c.get('structure', {}).get('flat_tokens', [])), ['B'])
        for target_structure in (structure_a, structure_c):
            context = extract_context_metadata(target_structure)
            self.assertEqual(context['context_ref_object_id'], '')
            self.assertEqual(context['context_owner_structure_id'], '')
            self.assertEqual(context['context_path_ids'], [])

        owner_a_db = self.hdb._structure_store.get_db_by_owner(atomic_a['id'])
        owner_c_db = self.hdb._structure_store.get_db_by_owner(atomic_c['id'])
        self.assertIsNotNone(owner_a_db)
        self.assertIsNotNone(owner_c_db)
        self.assertTrue(
            any(
                str(entry.get('entry_type', '') or '') == 'raw_residual'
                and str(entry.get('ext', {}).get('relation_type', '') or '') == 'stimulus_raw_residual'
                and str(entry.get('ext', {}).get('context_owner_structure_id', '') or '') == str(atomic_a['id'])
                for entry in owner_a_db.get('diff_table', [])
            )
        )
        self.assertTrue(
            any(
                str(entry.get('entry_type', '') or '') == 'raw_residual'
                and str(entry.get('ext', {}).get('relation_type', '') or '') == 'stimulus_raw_residual'
                and str(entry.get('ext', {}).get('context_owner_structure_id', '') or '') == str(atomic_c['id'])
                for entry in owner_c_db.get('diff_table', [])
            )
        )
        self.assertGreaterEqual(
            int(self.hdb._pointer_index.export_snapshot().get('exact_lookup_cache_count', 0) or 0),
            1,
        )

    def test_induction_energy_graph_v2_reinduces_root_and_propagates_frontier_layers(self):
        self.hdb._config['induction_energy_graph_v2_max_rounds'] = 4
        self.hdb._induction.update_config(self.hdb._config)
        structure_a = self._store_packet_as_structure(self._packet('A'), trace_id='graph_v2_seed_a')
        structure_ab = self._store_packet_as_structure(self._packet('AB'), trace_id='graph_v2_seed_ab')
        structure_abc = self._store_packet_as_structure(self._packet('ABC'), trace_id='graph_v2_seed_abc')

        self.assertIsNotNone(structure_a)
        self.assertIsNotNone(structure_ab)
        self.assertIsNotNone(structure_abc)

        self.hdb._structure_store.add_diff_entry(
            structure_a['id'],
            target_id=structure_ab['id'],
            content_signature=structure_ab.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='b',
            ext={'relation_type': 'incoming_extension'},
        )
        self.hdb._structure_store.add_diff_entry(
            structure_ab['id'],
            target_id=structure_abc['id'],
            content_signature=structure_abc.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='c',
            ext={'relation_type': 'incoming_extension'},
        )

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_graph_v2',
                    'ref_object_type': 'st',
                    'ref_object_id': structure_a['id'],
                    'display': 'A',
                    'er': 2.0,
                    'ev': 1.0,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='graph_v2_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )

        self.assertTrue(result['success'])
        data = result['data']
        self.assertTrue(data['energy_graph_v2_enabled'])
        self.assertEqual(data['energy_graph_config_max_rounds'], 4)
        self.assertGreaterEqual(data['energy_graph_round_count_max'], 2)
        self.assertGreaterEqual(data['energy_graph_depth_max'], 2)
        self.assertGreaterEqual(data['energy_graph_frontier_generated_count'], 1)
        self.assertGreaterEqual(data['energy_graph_root_reinduction_count'], 1)
        self.assertGreater(data['propagated_budget_total_ev'], data['total_ev_consumed'])

        ab_targets = [
            item for item in data['induction_targets']
            if item.get('target_structure_id') == structure_ab['id']
        ]
        abc_targets = [
            item for item in data['induction_targets']
            if item.get('target_structure_id') == structure_abc['id']
        ]
        self.assertTrue(ab_targets)
        self.assertTrue(abc_targets)
        self.assertTrue(any('er_induction' in (item.get('modes') or []) for item in ab_targets))
        self.assertTrue(any('ev_propagation' in (item.get('modes') or []) for item in ab_targets))
        self.assertTrue(any('ev_propagation' in (item.get('modes') or []) for item in abc_targets))
        self.assertTrue(any(int(item.get('energy_graph_depth_max', 0) or 0) >= 2 for item in abc_targets))

    def test_induction_energy_graph_v2_defaults_to_single_round_per_tick(self):
        structure_a = self._store_packet_as_structure(self._packet('A'), trace_id='graph_v2_default_seed_a')
        structure_ab = self._store_packet_as_structure(self._packet('AB'), trace_id='graph_v2_default_seed_ab')
        structure_abc = self._store_packet_as_structure(self._packet('ABC'), trace_id='graph_v2_default_seed_abc')

        self.assertIsNotNone(structure_a)
        self.assertIsNotNone(structure_ab)
        self.assertIsNotNone(structure_abc)

        self.hdb._structure_store.add_diff_entry(
            structure_a['id'],
            target_id=structure_ab['id'],
            content_signature=structure_ab.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='b',
            ext={'relation_type': 'incoming_extension'},
        )
        self.hdb._structure_store.add_diff_entry(
            structure_ab['id'],
            target_id=structure_abc['id'],
            content_signature=structure_abc.get('structure', {}).get('content_signature', ''),
            base_weight=1.0,
            residual_existing_signature='',
            residual_incoming_signature='c',
            ext={'relation_type': 'incoming_extension'},
        )

        state_snapshot = {
            'summary': {'active_item_count': 1},
            'top_items': [
                {
                    'id': 'runtime_source_graph_v2_default',
                    'ref_object_type': 'st',
                    'ref_object_id': structure_a['id'],
                    'display': 'A',
                    'er': 2.0,
                    'ev': 1.0,
                }
            ],
        }
        result = self.hdb.run_induction_propagation(
            state_snapshot=state_snapshot,
            trace_id='graph_v2_default_induction',
            max_source_items=1,
            enable_ev_propagation=True,
            enable_er_induction=True,
        )

        self.assertTrue(result['success'])
        data = result['data']
        self.assertTrue(data['energy_graph_v2_enabled'])
        self.assertEqual(data['energy_graph_config_max_rounds'], 1)
        self.assertEqual(data['energy_graph_round_count_max'], 1)
        self.assertEqual(data['energy_graph_depth_max'], 1)
        self.assertEqual(data['energy_graph_root_reinduction_count'], 0)

        ab_targets = [
            item for item in data['induction_targets']
            if item.get('target_structure_id') == structure_ab['id']
        ]
        abc_targets = [
            item for item in data['induction_targets']
            if item.get('target_structure_id') == structure_abc['id']
        ]
        self.assertTrue(ab_targets)
        self.assertFalse(abc_targets)

    def test_memory_activation_pool_merges_same_memory_id_across_modes(self):
        append_result = self.hdb.append_episodic_memory(
            episodic_payload={
                'event_summary': 'memory_for_activation',
                'structure_refs': ['st_a', 'st_b'],
                'group_refs': [],
            },
            trace_id='memory_pool_seed',
        )
        self.assertTrue(append_result['success'])
        memory_id = append_result['data']['episodic_id']

        apply_result = self.hdb.apply_memory_activation_targets(
            targets=[
                {
                    'projection_kind': 'memory',
                    'memory_id': memory_id,
                    'target_display_text': 'memory_for_activation',
                    'delta_ev': 0.4,
                    'sources': ['st_a'],
                    'modes': ['ev_propagation'],
                    'backing_structure_id': 'st_a',
                },
                {
                    'projection_kind': 'memory',
                    'memory_id': memory_id,
                    'target_display_text': 'memory_for_activation',
                    'delta_ev': 0.6,
                    'sources': ['st_b'],
                    'modes': ['er_induction'],
                    'backing_structure_id': 'st_b',
                },
            ],
            trace_id='memory_pool_apply',
        )
        self.assertTrue(apply_result['success'])
        self.assertEqual(apply_result['data']['applied_count'], 1)
        self.assertAlmostEqual(apply_result['data']['total_delta_ev'], 1.0, places=6)

        snapshot = self.hdb.get_memory_activation_snapshot(trace_id='memory_pool_snapshot', limit=8)
        self.assertTrue(snapshot['success'])
        self.assertEqual(snapshot['data']['summary']['count'], 1)
        item = snapshot['data']['items'][0]
        self.assertEqual(item['memory_id'], memory_id)
        self.assertAlmostEqual(item['ev'], 1.0, places=6)
        self.assertAlmostEqual(item['mode_totals']['ev_propagation'], 0.4, places=6)
        self.assertAlmostEqual(item['mode_totals']['er_induction'], 0.6, places=6)
        self.assertEqual(set(item['source_structure_ids']), {'st_a', 'st_b'})


if __name__ == '__main__':
    unittest.main()
