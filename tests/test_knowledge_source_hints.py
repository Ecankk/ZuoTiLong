import copy
import json
import unittest

import test_prepared_practice as fixtures
from app.bank.access import save_preferences
from app.knowledge import catalog, index
from app.knowledge.source_hints import for_sources
from app.learning.tasks import deliver, finish_task, task_package


class KnowledgeSourceHintsTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.PreparedPracticeTests()
        self.case.setUp()
        self.conn, self.f = self.case.conn, self.case.f
        self.case.start()
        self.case.read()
        saved = deliver(self.conn, self.f.root, self.f.data, self.case.payload(), self.f.lease)
        finish_task(self.conn, self.f.task['id'])
        self.conn.commit()
        self.selection_id = saved['result_id']
        self.probe = self.conn.execute('SELECT id FROM diagnostic_probes WHERE bank_id=?', (fixtures.BANK,)).fetchone()[0]
        self.f.start('organize_knowledge', contract_version='1.8')
        self.inputs = json.loads(self.f.task['input_json'])
        self.source = next(s for s in self.inputs['knowledge_sources'] if s['source_id'] == self.probe)

    def tearDown(self):
        self.case.tearDown()

    def hints(self, inputs=None, source=None):
        return for_sources(self.conn, inputs or self.inputs, [source or self.source])

    def payload(self):
        mappings = [{'source_id': s['source_id'], 'source_revision': s['source_revision'],
                     'topic_ids': [fixtures.TOPIC] if s['source_id'] == self.probe else [],
                     'event_topics': [{'event_id': e['id'], 'topic_ids': []} for e in s['events']],
                     'reason': 'Only the assigned chain-rule exercise is mapped; other evidence remains unlocalized.'}
                    for s in self.inputs['knowledge_sources']]
        return self.f.envelope({'summary': 'Mapped the assigned scope without new performance.',
                                'new_nodes': [], 'mappings': mappings, 'limitations': []})

    def test_known_ids_are_navigation_without_mutating_sources_or_learning_records(self):
        before = copy.deepcopy(self.inputs)
        changes = self.conn.total_changes
        hints = self.hints()
        self.assertEqual(len(hints), 1)
        self.assertEqual(hints[0]['selection_result_id'], self.selection_id)
        self.assertEqual(hints[0]['annotation_id'], self.case.annotation['id'])
        self.assertIn(fixtures.TOPIC, {t['id'] for t in hints[0]['question_topics']})
        self.assertIn(fixtures.TOPIC, {t['id'] for t in hints[0]['original_target_topics']})
        self.assertEqual(self.inputs, before)
        self.assertEqual(changes, self.conn.total_changes)
        self.assertNotIn('definition', hints[0]['question_topics'][0])
        self.assertNotIn('reference_reasoning', hints[0])

    def test_task_package_and_source_reader_offer_the_same_frozen_hints(self):
        package = task_package(self.conn, self.f.task['id'])
        response = self.case.tool('task_context', {'source_ids': [self.probe]})
        self.assertEqual(package['source_topic_hints'], response['source_topic_hints'])
        self.assertEqual(response['sources'], [self.source])
        reads = self.conn.execute("SELECT count(*) FROM task_reads WHERE task_id=? AND kind='knowledge_definition'",
                                  (self.f.task['id'],)).fetchone()[0]
        self.assertEqual(reads, 0)

    def test_hints_do_not_bypass_required_definition_reads_or_create_a_mapping(self):
        ids = [s['source_id'] for s in self.inputs['knowledge_sources']]
        self.case.tool('task_context', {'source_ids': ids})
        payload = self.payload()
        before = self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0]
        with self.assertRaisesRegex(ValueError, '读取'):
            deliver(self.conn, self.f.root, self.f.data, payload, self.f.lease)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0], before)

    def test_legacy_contract_and_nonexercise_sources_do_not_gain_fabricated_hints(self):
        old = copy.deepcopy(self.inputs)
        old['contract_version'] = '1.6'
        self.assertEqual(self.hints(inputs=old), [])
        original = next(s for s in index.sources(self.conn) if s['kind'] == 'question')
        self.assertEqual(self.hints(source=original), [])

    def test_forged_source_identity_cannot_borrow_another_selected_question(self):
        for mutate in ('bank', 'probe', 'result'):
            with self.subTest(mutate=mutate):
                source = copy.deepcopy(self.source)
                if mutate == 'bank':
                    source['content']['bank_id'] = 'unrelated-bank'
                elif mutate == 'probe':
                    source['content']['probe_id'] = 'unrelated-probe'
                else:
                    source['content']['assignment']['source_result_id'] = 'missing-result'
                self.assertEqual(self.hints(source=source), [])

    def test_changed_binding_proof_is_not_silently_accepted(self):
        row = self.conn.execute('SELECT payload_json FROM practice_question_bindings WHERE result_id=? AND probe_id=?',
                                (self.selection_id, self.probe)).fetchone()
        value = json.loads(row[0])
        value['annotation_content_revision'] = '0' * 64
        self.conn.execute('UPDATE practice_question_bindings SET payload_json=? WHERE result_id=? AND probe_id=?',
                          (json.dumps(value), self.selection_id, self.probe))
        self.assertEqual(self.hints(), [])

    def test_captured_definition_is_stable_and_newly_changed_definition_disables_hint(self):
        old = self.hints()
        node = next(n for n in catalog.document(self.conn)['document']['nodes'] if n['id'] == fixtures.TOPIC)
        self.case.m.change(fixtures.TOPIC, definition=node['definition'] + ' Changed mathematical premise.')
        self.assertEqual(self.hints(), old)
        fresh = copy.deepcopy(self.inputs)
        fresh['knowledge_catalog'] = index.catalog(self.conn)
        fresh['knowledge_catalog_revision'] = catalog.active_id(self.conn)
        self.assertEqual(self.hints(inputs=fresh), [])

    def test_hidden_student_material_remains_readable_internally_without_exposure(self):
        self.case.tool('task_context', {'source_ids': [s['source_id'] for s in self.inputs['knowledge_sources']]})
        self.case.tool('task_context', {'topic_ids': [fixtures.TOPIC]})
        deliver(self.conn, self.f.root, self.f.data, self.payload(), self.f.lease)
        finish_task(self.conn, self.f.task['id'])
        save_preferences(self.conn, {'study_type': 2, 'mask_same_type': True, 'reserved': []})
        self.conn.commit()
        self.f.start('prepare_practice', contract_version='1.9')
        before = {t: self.conn.execute('SELECT count(*) FROM ' + t).fetchone()[0]
                  for t in ('bank_views', 'bank_exposures', 'probe_attempts', 'learning_events')}
        result = self.case.tool('read_bank', {'bank_id': fixtures.BANK, 'role': 'all'})
        self.assertFalse(result['student_access']['can_view'])
        self.assertTrue(result['agent_access']['can_read'])
        self.assertFalse(result['agent_access']['student_mask_limits_agent'])
        self.assertTrue(result['agent_access']['ready_in_task_snapshot'])
        recalled = self.case.tool('catalog', {'topic_ids': [fixtures.TOPIC]})
        self.assertFalse(recalled['agent_access_policy']['student_mask_limits_agent'])
        self.assertTrue(recalled['agent_access_policy']['reserved_questions_excluded'])
        self.assertEqual(before, {t: self.conn.execute('SELECT count(*) FROM ' + t).fetchone()[0] for t in before})


if __name__ == '__main__':
    unittest.main()
