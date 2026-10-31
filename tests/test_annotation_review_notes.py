from app.learning.tasks import finish_task
import json
import unittest
import uuid

from app.bank import annotations
from app.knowledge.maintenance import normalize_scope
from app.learning.tasks import bind_turn, create_task, finish_task, retry_task, task_package
from app.learning.workflows import enqueue


class AnnotationReviewNoteTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f = QuestionPreparationTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.conn, self.root, self.data = self.f.conn, self.f.root, self.f.data
        self.f.prepare_catalog()
        self.ids = self.f.seed_questions()

    def start(self, note):
        self.f.start('annotate_questions', {'bank_ids': self.ids, 'review_note': note})
        return json.loads(self.f.task['input_json'])

    def test_optional_scope_does_not_add_a_field_to_existing_tasks(self):
        scope = {'bank_ids': self.ids}
        self.assertEqual(normalize_scope('annotate_questions', scope), scope)
        for version in annotations.SUPPORTED_RULE_REVISIONS:
            with self.subTest(version=version):
                value = annotations.capture(self.conn, self.data, scope, rule_revision=version)
                self.assertEqual(value['task_scope'], scope)
                self.assertNotIn('review_note', value['task_scope'])
                self.assertEqual(value['rule_revision'], version)

    def test_note_is_frozen_and_exposed_in_context_without_learning_writes(self):
        inputs = self.start('  核对链式法则的内层导数，不预设结论。  ')
        expected = '核对链式法则的内层导数，不预设结论。'
        self.assertEqual(inputs['task_scope']['review_note'], expected)
        before = self.conn.total_changes
        value = task_package(self.conn, self.f.task['id'])
        self.assertEqual(value['input']['task_scope']['review_note'], expected)
        self.assertEqual(self.conn.total_changes, before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0], 0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0], 0)

    def test_note_does_not_replace_actual_material_and_definition_reading(self):
        self.start('待核建议：导数可能为0，仍须独立读题并验证。')
        value = self.f.envelope(self.f.annotation_result())
        with self.assertRaises(ValueError):
            self.f.tool('apply_report', {'result': value})
        self.f.read_annotation_material()
        self.f.tool('apply_report', {'result': value})
        finish_task(self.conn, self.f.task['id'])
        self.conn.commit()
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        saved = annotations.current(self.conn, self.data, self.ids[0])['analysis']
        self.assertEqual(saved['status'], 'ready')
        self.assertIn('2x cos(x²)', saved['reference_reasoning'])
        self.assertNotIn('review_note', saved)
        self.assertNotIn('review_note', saved['fingerprint'])

    def test_note_can_still_result_in_a_review_required_annotation(self):
        self.start('复核后如仍有材料缺口，保留未就绪。')
        self.f.read_annotation_material()
        self.f.tool('apply_report', {'result': self.f.envelope(self.f.annotation_result('needs_review'))})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        saved = annotations.current(self.conn, self.data, self.ids[0])['analysis']
        self.assertEqual(saved['status'], 'needs_review')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0], 0)

    def test_same_request_cannot_silently_replace_the_review_question(self):
        request = str(uuid.uuid4())
        scope = {'bank_ids': self.ids, 'review_note': '核对内层导数。'}
        first = create_task(self.conn, self.root, self.data, 'annotate_questions', None, 'same-session', request, task_scope=scope)
        repeated = create_task(self.conn, self.root, self.data, 'annotate_questions', None, 'same-session', request, task_scope=scope)
        self.assertEqual(first['id'], repeated['id'])
        before = self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0]
        with self.assertRaises(ValueError):
            create_task(self.conn, self.root, self.data, 'annotate_questions', None, 'same-session', request,
                        task_scope={**scope, 'review_note': '改为核对另一个结论。'})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0], before)

    def test_invalid_or_unscoped_notes_are_rejected(self):
        for note in (None, True, 3, [], {}, '', '  ', 'x' * 4001):
            with self.subTest(note_type=type(note).__name__, length=len(note) if isinstance(note, str) else None):
                with self.assertRaises(ValueError):
                    annotations.capture(self.conn, self.data, {'bank_ids': self.ids, 'review_note': note})
        with self.assertRaises(ValueError):
            normalize_scope('annotate_questions', {'review_note': '没有明确题号范围。'})
        with self.assertRaises(ValueError):
            normalize_scope('annotate_questions', {'bank_ids': self.ids, 'review_note': '待核。', 'expected_result': 'ready'})

    def test_durable_queue_retains_the_normalized_note_until_dispatch(self):
        request = str(uuid.uuid4())
        job = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, request,
                      task_scope={'bank_ids': self.ids, 'review_note': '  核对原图的具体步骤。  '})
        stored = self.conn.execute('SELECT * FROM workflow_jobs WHERE id=?', (job['id'],)).fetchone()
        scope = json.loads(stored['scope_json'])
        self.assertEqual(scope['review_note'], '核对原图的具体步骤。')
        task = create_task(self.conn, self.root, self.data, stored['kind'], None, 'same-session', request,
                           workflow_id=stored['workflow_id'], task_scope=scope)
        self.assertEqual(json.loads(task['input_json'])['task_scope'], scope)

    def test_retry_preserves_note_and_input_revision_with_original_delivery_rules(self):
        inputs = self.start('本轮只复核内层求导，结论仍独立检查。')
        revision = self.f.task['input_revision']
        task = retry_task(self.conn, self.root, self.data, self.f.task['id'])
        self.assertEqual(task['input_revision'], revision)
        self.assertEqual(json.loads(task['input_json'])['task_scope'], inputs['task_scope'])
        bind_turn(self.conn, task['id'], 'same-session', task['run_token'], 'review-note-retry')
        self.conn.commit()
        self.f.task = task
        self.f.lease.update(run_token=task['run_token'], turn_id='review-note-retry')
        self.f.read_annotation_material()
        self.f.tool('apply_report', {'result': self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn, task['id'])
        self.conn.commit()
        self.assertEqual(annotations.current(self.conn, self.data, self.ids[0])['analysis']['status'], 'ready')

    def test_queued_reviews_with_different_notes_are_not_merged(self):
        first = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, str(uuid.uuid4()),
                        task_scope={'bank_ids': self.ids, 'review_note': '核对题干的条件。'})
        same = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, str(uuid.uuid4()),
                       task_scope={'bank_ids': self.ids, 'review_note': '  核对题干的条件。  '})
        other = enqueue(self.conn, self.root, self.data, 'annotate_questions', None, str(uuid.uuid4()),
                        task_scope={'bank_ids': self.ids, 'review_note': '核对解析的链式法则。'})
        self.assertEqual(first['id'], same['id'])
        self.assertNotEqual(first['id'], other['id'])
        with self.assertRaises(ValueError):
            enqueue(self.conn, self.root, self.data, 'annotate_questions', None, first['request_id'],
                    task_scope={'bank_ids': self.ids, 'review_note': '替换原先具体复核问题。'})


if __name__ == '__main__':
    unittest.main()
