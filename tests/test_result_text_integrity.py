import copy
import json
import unittest
from unittest.mock import patch

from app.learning.tasks import deliver, finish_task, receipt


class ResultTextIntegrityTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f = QuestionPreparationTests()
        self.f.setUp()
        self.f.prepare_catalog()
        self.ids = self.f.seed_questions()
        self.start()

    def tearDown(self):
        self.f.tearDown()

    def start(self, revision=None):
        scope = {'bank_ids': self.ids}
        if revision:
            scope['revision'] = revision
        self.f.start('annotate_questions', scope)
        self.f.read_annotation_material()

    def save(self, value):
        return deliver(self.f.conn, self.f.root, self.f.data, self.f.envelope(value), self.f.lease)

    def test_non_display_controls_reject_before_receipt_and_allow_same_task_repair(self):
        for control in ('\x00', '\b', '\v', '\f', '\x1f', '\x7f'):
            with self.subTest(code=ord(control)):
                value = self.f.annotation_result()
                value['questions'][0]['bindings'][0]['evidence'] = '集合 ' + control + 'arnothing'
                with self.assertRaisesRegex(ValueError, r'result/questions/0/bindings/0/evidence.*U\+'):
                    self.save(value)
                self.assertIsNone(receipt(self.f.conn, self.f.task['id']))
                self.assertEqual(self.f.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 0)
        corrected = self.f.annotation_result()
        corrected['questions'][0]['bindings'][0]['evidence'] = r'应用链式法则；集合记号 \(A\cap B=\varnothing\)。'
        self.save(corrected)
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 1)
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0], 0)

    def test_valid_unicode_multiline_whitespace_and_tex_are_saved_verbatim(self):
        value = self.f.annotation_result()
        text = '中文 ∅ α ≤\r\n下一行\t' + r'\(\bar A\cup\bar B=\Omega\)'
        value['questions'][0]['reference_reasoning'] = text
        self.save(value)
        saved = json.loads(self.f.conn.execute('SELECT payload_json FROM question_annotations').fetchone()[0])
        self.assertEqual(saved['reference_reasoning'], text)

    def test_historical_receipt_replay_keeps_original_bytes(self):
        value = self.f.annotation_result()
        value['questions'][0]['bindings'][0]['evidence'] = '历史\v损坏'
        with patch('app.learning.tasks.validate_result_text'):
            original = self.save(value)
        replay = self.save(value)
        self.assertTrue(replay['reused'])
        self.assertEqual(replay['result_id'], original['result_id'])
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 1)

    def test_frozen_legacy_field_can_stay_but_cannot_copy_corruption_to_new_field(self):
        value = self.f.annotation_result()
        value['questions'][0]['bindings'][0]['evidence'] = '冻结\b原字段'
        with patch('app.learning.tasks.validate_result_text'):
            self.save(value)
        finish_task(self.f.conn, self.f.task['id'])
        self.f.conn.commit()
        previous = self.f.conn.execute('SELECT id FROM question_annotations ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        self.start({'expected_annotations': {self.ids[0]: previous}, 'allowed_fields': ['reference_reasoning']})
        base = copy.deepcopy(json.loads(self.f.task['input_json'])['bank_questions'][0]['revision_base']['analysis'])
        result = {'summary': '仅修订推导。', 'questions': [base], 'limitations': []}
        result['questions'][0]['reference_reasoning'] = '新字段\b不能复制损坏'
        with self.assertRaisesRegex(ValueError, r'reference_reasoning.*U\+0008'):
            self.save(result)
        self.assertIsNone(receipt(self.f.conn, self.f.task['id']))
        result['questions'][0]['reference_reasoning'] = '有效的有限范围推导修订。'
        self.save(result)
        self.assertEqual(self.f.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 2)
        last = json.loads(self.f.conn.execute('SELECT payload_json FROM question_annotations ORDER BY rowid DESC LIMIT 1').fetchone()[0])
        self.assertEqual(last['bindings'][0]['evidence'], '冻结\b原字段')

    def test_catalogue_definition_control_rolls_back_publication_and_receipt(self):
        self.save(self.f.annotation_result())
        finish_task(self.f.conn, self.f.task['id'])
        self.f.conn.commit()
        self.f.start('maintain_catalog', {'source_version_id': self.f.f.sid, 'source_ids': ['GS-04-001']})
        self.f.tool('task_context', {'source_ids': ['GS-04-001']})
        from app.knowledge import catalog
        previous = catalog.active_id(self.f.conn)
        value = self.f.maintenance_result()
        value['node_changes'][0]['definition'] = '错误\f公式'
        with self.assertRaisesRegex(ValueError, r'node_changes/0/definition.*U\+000C'):
            self.save(value)
        self.assertEqual(catalog.active_id(self.f.conn), previous)
        self.assertIsNone(receipt(self.f.conn, self.f.task['id']))
