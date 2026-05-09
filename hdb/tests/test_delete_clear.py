# -*- coding: utf-8 -*-

from collections import deque
import glob
import os
import shutil
import tempfile
import unittest

from hdb import HDB


class TestHDBDeleteClear(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_delete_clear_')
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})

    def tearDown(self):
        if getattr(self, 'hdb', None) is not None:
            self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _packet(self, text: str) -> dict:
        sa_items = []
        for idx, ch in enumerate(text):
            sa_items.append({
                'id': f'sa_dc_{idx}',
                'object_type': 'sa',
                'content': {'raw': ch, 'display': ch, 'normalized': ch},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': idx}},
            })
        return {
            'id': f'spkt_dc_{text}',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_dc', 'sa_ids': [item['id'] for item in sa_items], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def test_delete_and_clear_full_remove_runtime_artifacts(self):
        result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好'), trace_id='dc_seed')
        structure_id = (result['data']['new_structure_ids'] or result['data'].get('seeded_atomic_structure_ids', []))[0]

        delete_result = self.hdb.delete_structure(structure_id=structure_id, trace_id='dc_delete', delete_mode='safe_detach')
        self.assertTrue(delete_result['success'])
        self.assertTrue(delete_result['data']['deleted'])

        query = self.hdb.query_structure_database(structure_id=structure_id, trace_id='dc_query')
        self.assertFalse(query['success'])

        self.hdb._register_issue({'issue_type': 'manual_test_issue', 'target_id': structure_id})
        repair = self.hdb.repair_hdb(trace_id='dc_repair', repair_scope='global_quick', background=False)
        self.assertTrue(repair['success'])
        self.assertEqual(repair['data']['status'], 'completed')
        self.assertTrue(glob.glob(os.path.join(self.temp_dir, 'repair', 'repair_job_*.json')))

        clear_result = self.hdb.clear_hdb(trace_id='dc_clear', reason='unit_test_reset', operator='tester', clear_mode='full')
        self.assertTrue(clear_result['success'])
        self.assertGreaterEqual(clear_result['data']['cleared_repair_file_count'], 1)

        self.hdb.close()
        self.hdb = None

        reopened = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})
        try:
            snapshot = reopened.get_hdb_snapshot(trace_id='dc_snapshot')['data']
            self.assertEqual(snapshot['summary']['structure_count'], 0)
            self.assertEqual(snapshot['summary']['group_count'], 0)
            self.assertEqual(snapshot['summary']['episodic_count'], 0)
            self.assertEqual(snapshot['summary']['issue_count'], 0)
            self.assertEqual(len(reopened._repair.jobs), 0)
            self.assertFalse(glob.glob(os.path.join(self.temp_dir, 'repair', 'repair_job_*.json')))
        finally:
            reopened.close()

    def test_clear_full_removes_orphan_structure_databases(self):
        orphan_dir = os.path.join(self.temp_dir, 'indexes')
        os.makedirs(orphan_dir, exist_ok=True)
        orphan_path = os.path.join(orphan_dir, 'sdb_999999.json')
        with open(orphan_path, 'w', encoding='utf-8') as fh:
            fh.write('{"structure_db_id":"sdb_999999","owner_structure_id":"st_missing","diff_table":[]}')

        clear_result = self.hdb.clear_hdb(trace_id='dc_clear_orphan', reason='unit_test_reset', operator='tester', clear_mode='full')

        self.assertTrue(clear_result['success'])
        self.assertFalse(os.path.exists(orphan_path))

    def test_reopen_ignores_orphan_structure_databases(self):
        self.hdb.close()
        self.hdb = None

        indexes_dir = os.path.join(self.temp_dir, 'indexes')
        os.makedirs(indexes_dir, exist_ok=True)
        orphan_path = os.path.join(indexes_dir, 'sdb_999998.json')
        with open(orphan_path, 'w', encoding='utf-8') as fh:
            fh.write('{"structure_db_id":"sdb_999998","owner_structure_id":"st_missing","diff_table":[{"display_text":"' + ('你好' * 1000) + '"}]}')

        reopened = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})
        try:
            snapshot = reopened.get_hdb_snapshot(trace_id='dc_snapshot_orphan')['data']
            self.assertEqual(snapshot['summary']['structure_count'], 0)
            self.assertEqual(snapshot['summary']['structure_db_count'], 0)
            self.assertTrue(os.path.exists(orphan_path))
        finally:
            reopened.close()

    def test_cam_display_fallback_filters_display_joiners_from_internal_fragments(self):
        item = {
            'id': 'spi_display_pollution',
            'item_id': 'spi_display_pollution',
            'ref_object_id': 'st_display_pollution',
            'ref_object_type': 'st',
            'display': '{【用户】 + + + 我 + 。 + 【助手回复】 + 好} · structure',
            'er': 1.0,
            'ev': 0.0,
        }

        result = self.hdb._structure_retrieval._run_cam_internal_stimulus_only(
            items=[item],
            trace_id='dc_display_filter',
            tick_id='tick_dc_display_filter',
            cut_engine=self.hdb._cut,
        )

        self.assertTrue(result['internal_stimulus_fragments'])
        fragment = result['internal_stimulus_fragments'][0]
        self.assertTrue(fragment.get('ext', {}).get('display_fallback_char_split'))
        self.assertNotIn('+', fragment.get('flat_tokens', []))

        packet = self.hdb._cut.build_internal_stimulus_packet(
            result['internal_stimulus_fragments'],
            trace_id='dc_display_filter_packet',
            tick_id='tick_dc_display_filter',
        )
        packet_tokens = [str(item.get('content', {}).get('raw', '')) for item in packet.get('sa_items', [])]
        self.assertNotIn('+', packet_tokens)
        self.assertIn('我', packet_tokens)
        self.assertIn('好', packet_tokens)

    def test_cam_display_fallback_preserves_standalone_attribute_sa_as_attribute_unit(self):
        item = {
            'id': 'spi_attr_reward_signal',
            'item_id': 'spi_attr_reward_signal',
            'ref_object_id': 'sa_attr_reward_signal_runtime',
            'ref_object_type': 'sa',
            'display': '奖励信号:0.8',
            'er': 0.0,
            'ev': 0.8,
            'ref_snapshot': {
                'content_display': '奖励信号:0.8',
                'role': 'attribute',
                'attribute_name': 'reward_signal',
                'attribute_value': 0.8,
                'value_type': 'numerical',
            },
        }

        result = self.hdb._structure_retrieval._run_cam_internal_stimulus_only(
            items=[item],
            trace_id='dc_attr_fallback',
            tick_id='tick_dc_attr_fallback',
            cut_engine=self.hdb._cut,
        )

        self.assertTrue(result['internal_stimulus_fragments'])
        fragment = result['internal_stimulus_fragments'][0]
        self.assertFalse(fragment.get('ext', {}).get('display_fallback_char_split'))
        self.assertIn('reward_signal:0.8', [str(token) for token in (fragment.get('flat_tokens', []) or [])])

        packet = self.hdb._cut.build_internal_stimulus_packet(
            result['internal_stimulus_fragments'],
            trace_id='dc_attr_fallback_packet',
            tick_id='tick_dc_attr_fallback',
        )
        attribute_items = [
            row
            for row in packet.get('sa_items', [])
            if (row.get('stimulus', {}) or {}).get('role') == 'attribute'
        ]
        self.assertTrue(attribute_items)
        self.assertEqual(attribute_items[0].get('content', {}).get('attribute_name'), 'reward_signal')

    def test_internal_packet_only_skips_display_joiners_for_marked_fallback_fragments(self):
        base_fragment = {
            'fragment_id': 'frag_plus',
            'sequence_groups': [
                {
                    'group_index': 0,
                    'source_type': 'internal',
                    'origin_frame_id': 'frag_plus',
                    'tokens': ['A', '+', 'B'],
                }
            ],
            'flat_tokens': ['A', '+', 'B'],
            'er_hint': 1.0,
            'ev_hint': 0.0,
            'ext': {},
        }

        raw_packet = self.hdb._cut.build_internal_stimulus_packet(
            [base_fragment],
            trace_id='dc_real_plus',
            tick_id='tick_dc_real_plus',
        )
        raw_tokens = [str(item.get('content', {}).get('raw', '')) for item in raw_packet.get('sa_items', [])]
        self.assertEqual(raw_tokens, ['A', '+', 'B'])

        fallback_fragment = dict(base_fragment)
        fallback_fragment['ext'] = {'display_fallback_char_split': True}
        filtered_packet = self.hdb._cut.build_internal_stimulus_packet(
            [fallback_fragment],
            trace_id='dc_filtered_plus',
            tick_id='tick_dc_filtered_plus',
        )
        filtered_tokens = [str(item.get('content', {}).get('raw', '')) for item in filtered_packet.get('sa_items', [])]
        self.assertEqual(filtered_tokens, ['A', 'B'])

    def test_clear_hdb_full_resets_runtime_caches(self):
        self.hdb._structure_retrieval._internal_resolution_cursor['st_demo'] = 3
        self.hdb._structure_retrieval._internal_resolution_history['st_demo'] = deque(['F:A'])
        self.hdb._structure_retrieval._internal_resolution_history_counts['st_demo'] = {'F:A': 1}
        self.hdb._structure_retrieval._internal_resolution_focus_credit['st_demo'] = 1.5
        self.hdb._stimulus._runtime_cache = {'structure_profiles': {'demo': {}}}

        clear_result = self.hdb.clear_hdb(
            trace_id='dc_clear_runtime',
            reason='unit_test_reset',
            operator='tester',
            clear_mode='full',
        )

        runtime_reset = clear_result['data']['runtime_reset']
        self.assertEqual(runtime_reset['structure_retrieval']['internal_resolution_cursor_count'], 1)
        self.assertEqual(runtime_reset['structure_retrieval']['internal_resolution_history_count'], 1)
        self.assertEqual(runtime_reset['structure_retrieval']['internal_resolution_history_bucket_count'], 1)
        self.assertEqual(runtime_reset['structure_retrieval']['internal_resolution_focus_credit_count'], 1)
        self.assertTrue(runtime_reset['stimulus_retrieval']['had_runtime_cache'])
        self.assertEqual(self.hdb._structure_retrieval._internal_resolution_cursor, {})
        self.assertEqual(self.hdb._structure_retrieval._internal_resolution_history, {})
        self.assertEqual(self.hdb._structure_retrieval._internal_resolution_history_counts, {})
        self.assertEqual(self.hdb._structure_retrieval._internal_resolution_focus_credit, {})
        self.assertIsNone(self.hdb._stimulus._runtime_cache)


if __name__ == '__main__':
    unittest.main()
