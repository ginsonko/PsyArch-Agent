# -*- coding: utf-8 -*-

import shutil
import tempfile
import unittest

from hdb import HDB
from state_pool.main import StatePool
from text_sensor import TextSensor


class TestHDBIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix='hdb_integration_')
        self.sensor = TextSensor(config_override={'default_mode': 'simple', 'enable_echo': False, 'enable_token_output': False, 'enable_char_output': True})
        self.pool = StatePool(config_override={'enable_placeholder_interfaces': False, 'enable_script_broadcast': False})
        self.hdb = HDB(config_override={'data_dir': self.temp_dir, 'enable_background_repair': False})

    def tearDown(self):
        self.sensor._logger.close()
        self.pool._logger.close()
        self.hdb.close()
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _project_runtime_structures(self, projections, trace_id):
        for item in projections:
            runtime_object = self.hdb.make_runtime_structure_object(item['structure_id'], er=item.get('er', 0.0), ev=item.get('ev', 0.0), reason=item.get('reason', 'test_projection'))
            if runtime_object:
                result = self.pool.insert_runtime_node(runtime_object=runtime_object, trace_id=trace_id, source_module='hdb', reason=item.get('reason', 'test_projection'))
                self.assertTrue(result['success'])

    def test_text_sensor_state_pool_hdb_smoke(self):
        sensor_result = self.sensor.ingest_text(text='你好呀！', trace_id='int_t1', tick_id='int_t1')
        self.assertTrue(sensor_result['success'])
        packet = sensor_result['data']['stimulus_packet']

        pool_result = self.pool.apply_stimulus_packet(stimulus_packet=packet, trace_id='int_t1', tick_id='int_t1', source_module='text_sensor')
        self.assertTrue(pool_result['success'])

        snapshot = self.pool.get_state_snapshot(trace_id='int_snap1')['data']['snapshot']
        structure_result = self.hdb.run_structure_level_retrieval_storage(state_snapshot=snapshot, trace_id='int_struct')
        self.assertTrue(structure_result['success'])

        stimulus_result = self.hdb.run_stimulus_level_retrieval_storage(stimulus_packet=packet, trace_id='int_stim')
        self.assertTrue(stimulus_result['success'])
        self._project_runtime_structures(stimulus_result['data']['runtime_projection_structures'], 'int_project')

        snapshot2 = self.pool.get_state_snapshot(trace_id='int_snap2')['data']['snapshot']
        st_items = [item for item in snapshot2['top_items'] if item.get('ref_object_type') == 'st']
        self.assertTrue(st_items)

        induction = self.hdb.run_induction_propagation(state_snapshot=snapshot2, trace_id='int_ind')
        self.assertTrue(induction['success'])


if __name__ == '__main__':
    unittest.main()
