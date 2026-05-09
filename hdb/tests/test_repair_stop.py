# -*- coding: utf-8 -*-

import shutil
import tempfile
import time
import unittest

from hdb import HDB


class TestHDBRepairStop(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_repair_stop_')
        self.hdb = HDB(config_override={
            'data_dir': self.temp_dir,
            'enable_background_repair': True,
            'repair_sleep_ms_between_batches': 50,
        })

    def tearDown(self):
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _packet(self, text: str) -> dict:
        sa_items = []
        for idx, ch in enumerate(text):
            sa_items.append({
                'id': f'sa_rs_{idx}_{ord(ch)}',
                'object_type': 'sa',
                'content': {'raw': ch, 'display': ch, 'normalized': ch},
                'stimulus': {'role': 'feature', 'modality': 'text'},
                'energy': {'er': 1.0, 'ev': 0.0},
                'ext': {'packet_context': {'sequence_index': idx}},
            })
        return {
            'id': f'spkt_rs_{text}',
            'object_type': 'stimulus_packet',
            'sa_items': sa_items,
            'csa_items': [],
            'grouped_sa_sequences': [
                {'group_index': 0, 'source_type': 'current', 'origin_frame_id': 'frame_rs', 'sa_ids': [item['id'] for item in sa_items], 'csa_ids': []}
            ],
            'energy_summary': {'current_total_er': float(len(sa_items)), 'current_total_ev': 0.0},
            'source': {'parent_ids': []},
        }

    def test_background_repair_can_be_stopped(self):
        for text in ['甲乙', '丙丁', '戊己', '庚辛', '壬癸']:
            self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=self._packet(text), trace_id=f'rs_seed_{text}')

        start = self.hdb.repair_hdb(trace_id='rs_start', repair_scope='global_quick', batch_limit=1, background=True)
        self.assertTrue(start['success'])
        job_id = start['data']['repair_job_id']

        stop = self.hdb.stop_repair_job(repair_job_id=job_id, trace_id='rs_stop')
        self.assertTrue(stop['success'])

        for _ in range(20):
            status = self.hdb._repair.jobs[job_id]['status']
            if status in {'stopped', 'completed', 'failed', 'timeout'}:
                break
            time.sleep(0.05)

        self.assertIn(self.hdb._repair.jobs[job_id]['status'], {'stopped', 'completed'})


if __name__ == '__main__':
    unittest.main()
