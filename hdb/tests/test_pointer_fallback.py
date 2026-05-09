# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB


class TestHDBPointerFallback(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_pointer_fallback_')
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _packet(self, text: str) -> dict:
        sa_items = []
        for idx, ch in enumerate(text):
            sa_items.append({
                'id': f'sa_pf_{idx}',
                'object_type': 'sa',
                'content': {'raw': ch, 'display': ch, 'normalized': ch},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': idx}},
            })
        return {
            'id': f'spkt_pf_{text}',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_pf', 'sa_ids': [item['id'] for item in sa_items], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def test_signature_index_fallback_restores_query_path(self):
        result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet('你好呀'), trace_id='pf_seed')
        structure_id = (result['data']['new_structure_ids'] or result['data'].get('seeded_atomic_structure_ids', []))[0]

        structure_obj = self.hdb._structure_store.get(structure_id)
        structure_obj['db_pointer']['structure_db_id'] = 'sdb_missing_signature'
        self.hdb._structure_store.update_structure(structure_obj)
        self.hdb._pointer_index._primary_map.pop(structure_id, None)
        self.hdb._pointer_index._fallback_map.pop(structure_id, None)
        self.hdb._pointer_index._recent_cache.pop(structure_id, None)

        query = self.hdb.query_structure_database(structure_id=structure_id, trace_id='pf_query')
        self.assertTrue(query['success'])
        self.assertTrue(query['data']['pointer_info']['used_fallback'])
        self.assertEqual(query['data']['pointer_info']['fallback_mode'], 'signature_index')


if __name__ == '__main__':
    unittest.main()
