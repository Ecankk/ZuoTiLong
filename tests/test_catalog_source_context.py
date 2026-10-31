"""Source metadata makes re-curation local without weakening actual-reading gates."""
import copy
import json
import unittest
from app.knowledge import catalog
from app.knowledge.maintenance import source_context
from app.learning.tasks import finish_task, receipt


class CatalogSourceContextTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f = QuestionPreparationTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.conn = self.f.conn

    def start(self):
        self.f.start('maintain_catalog', {'source_version_id': self.f.f.sid, 'source_ids': ['GS-04-001']})

    def test_unreviewed_source_has_no_invented_associations(self):
        self.start()
        inputs = json.loads(self.f.task['input_json'])
        result = self.f.tool('task_context', {'source_ids': ['GS-04-001']})
        self.assertEqual(result['source_entries'], inputs['source_entries'])
        self.assertEqual(result['existing_source_resolutions'], [])
        self.assertEqual(result['related_nodes'], [])
        self.assertEqual(result['catalog_revision'], inputs['catalog_revision'])

    def test_association_metadata_does_not_grant_actual_definition_read(self):
        self.f.prepare_catalog()
        self.start()
        result = self.f.tool('task_context', {'source_ids': ['GS-04-001']})
        self.assertEqual(result['existing_source_resolutions'][0]['node_ids'], ['GS-04-001'])
        self.assertEqual(result['related_nodes'][0]['id'], 'GS-04-001')
        self.assertNotIn('definition', result['related_nodes'][0])
        value = self.f.envelope(self.f.maintenance_result())
        with self.assertRaisesRegex(ValueError, '尚未读取'):
            self.f.tool('apply_report', {'result': value})
        self.assertIsNone(receipt(self.conn, self.f.task['id']))
        self.f.tool('task_context', {'topic_ids': ['GS-04-001']})
        self.f.tool('apply_report', {'result': value})
        self.assertIsNotNone(receipt(self.conn, self.f.task['id']))

    def test_complete_old_associations_preserve_unchanged_node_and_use_captured_revision(self):
        self.f.prepare_catalog()
        value = copy.deepcopy(catalog.document(self.conn)['document'])
        second = copy.deepcopy(next(n for n in value['nodes'] if n['id'] == 'GS-04-001'))
        second.update(id='GS-04-001.conditions', name='链式求导各复合层的可导条件', aliases=[])
        value['nodes'].append(second)
        value['source_resolutions'][0]['node_ids'].append(second['id'])
        self.f.f.publish(value)
        self.conn.commit()
        self.start()
        inputs = json.loads(self.f.task['input_json'])
        metadata = self.f.tool('task_context', {'source_ids': ['GS-04-001']})
        self.assertEqual(set(metadata['existing_source_resolutions'][0]['node_ids']), {'GS-04-001', second['id']})
        self.f.tool('task_context', {'topic_ids': ['GS-04-001', second['id']]})
        result = self.f.maintenance_result()
        # The old helper lists only the changed node, which would silently
        # discard the other association if the consistency guard were absent.
        with self.assertRaisesRegex(ValueError, '来源.*不一致'):
            self.f.tool('apply_report', {'result': self.f.envelope(result)})
        result['source_resolutions'] = metadata['existing_source_resolutions']
        self.f.tool('apply_report', {'result': self.f.envelope(result)})
        finish_task(self.conn, self.f.task['id'])
        self.conn.commit()
        current = catalog.document(self.conn)
        self.assertIn(second, current['document']['nodes'])
        old = source_context(inputs, ['GS-04-001'])
        self.assertEqual(old['catalog_revision'], inputs['catalog_revision'])
        self.assertNotEqual(old['catalog_revision'], current['id'])
        self.assertEqual(old['existing_source_resolutions'], metadata['existing_source_resolutions'])
