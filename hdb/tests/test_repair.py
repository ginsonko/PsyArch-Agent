# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestHDBRepair(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_repair_')
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})
        packet = {
            'id': 'spkt_repair',
            'object_type': 'stimulus_packet',
            'sa_items': [
                {'id': 'sa_1', 'object_type': 'sa', 'content': {'raw': '你', 'display': '你', 'normalized': '你'}, 'stimulus': {'role': 'feature', 'modality': 'text'}, 'energy': {'er': 1.0, 'ev': 0.0}, 'ext': {'packet_context': {'sequence_index': 0}}},
                {'id': 'sa_2', 'object_type': 'sa', 'content': {'raw': '好', 'display': '好', 'normalized': '好'}, 'stimulus': {'role': 'feature', 'modality': 'text'}, 'energy': {'er': 1.0, 'ev': 0.0}, 'ext': {'packet_context': {'sequence_index': 1}}},
            ],
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_repair', 'sa_ids': ['sa_1', 'sa_2'], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': 2.0, 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }
        result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='repair_seed')
        self.structure_id = (result['data']['new_structure_ids'] or result['data'].get('seeded_atomic_structure_ids', []))[0]

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_targeted_repair_rebuilds_pointer(self):
        structure_obj = self.hdb._structure_store.get(self.structure_id)
        structure_obj['db_pointer']['structure_db_id'] = 'sdb_missing_broken'
        self.hdb._structure_store.update_structure(structure_obj)

        check = self.hdb.self_check_hdb(trace_id='repair_check', target_id=self.structure_id)
        self.assertGreaterEqual(check['data']['issue_count'], 1)

        repair = self.hdb.repair_hdb(trace_id='repair_run', target_id=self.structure_id, repair_scope='targeted', repair_actions=['rebuild_pointer'], background=False)
        self.assertTrue(repair['success'])
        self.assertEqual(repair['data']['status'], 'completed')

        query = self.hdb.query_structure_database(structure_id=self.structure_id, trace_id='repair_query')
        self.assertTrue(query['success'])

    def test_targeted_repair_refreshes_memory_activation_refs(self):
        episodic = self.hdb._episodic_store.append(
            {
                'event_summary': 'repair memory activation',
                'structure_refs': [self.structure_id],
                'group_refs': [],
                'meta': {'ext': {'memory_material': {'memory_kind': 'structure_group'}}},
            },
            trace_id='repair_em',
        )
        memory_id = episodic['id']
        self.hdb._memory_activation_store._items[memory_id] = {
            'id': memory_id,
            'memory_id': memory_id,
            'object_type': 'memory_activation',
            'display_text': memory_id,
            'event_summary': episodic['event_summary'],
            'structure_refs': ['st_missing'],
            'group_refs': ['sg_missing'],
            'backing_structure_ids': ['st_missing'],
            'source_structure_ids': ['st_missing'],
            'er': 0.0,
            'ev': 1.0,
            'last_delta_er': 0.0,
            'last_delta_ev': 1.0,
            'last_decay_delta_er': 0.0,
            'last_decay_delta_ev': 0.0,
            'total_delta_er': 0.0,
            'total_delta_ev': 1.0,
            'hit_count': 1,
            'update_count': 1,
            'mode_totals': {},
            'mode_totals_er': {},
            'mode_totals_ev': {},
            'recent_events': [],
            'feedback_count': 0,
            'last_feedback_er': 0.0,
            'last_feedback_ev': 0.0,
            'total_feedback_er': 0.0,
            'total_feedback_ev': 0.0,
            'last_feedback_at': 0,
            'recent_feedback_events': [],
            'created_at': 0,
            'last_updated_at': 0,
            'last_trace_id': '',
            'last_tick_id': '',
        }

        repair = self.hdb.repair_hdb(
            trace_id='repair_mem_run',
            target_id=memory_id,
            repair_scope='targeted',
            repair_actions=['refresh_memory_activation_refs'],
            background=False,
        )
        self.assertTrue(repair['success'])
        item = self.hdb._memory_activation_store.get(memory_id)
        self.assertEqual(item['structure_refs'], [self.structure_id])
        self.assertEqual(item['group_refs'], [])
        self.assertEqual(item['backing_structure_ids'], [])
        self.assertEqual(item['source_structure_ids'], [])


if __name__ == '__main__':
    unittest.main()
