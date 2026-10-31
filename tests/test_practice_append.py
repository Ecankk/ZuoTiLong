import copy
import json
from io import BytesIO
import unittest
from unittest.mock import patch

from PIL import Image
from app.storage.images import save_answer_image

import test_learning_tasks as fixtures
from app.bank.access import init_access, reveal
from app.learning.contracts import validate_result
from app.learning.loop import loop_snapshot, submit_probe
from app.learning.tasks import deliver, finish_task, record_read, resource_digest, task_package


class PracticeAppendTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningTaskTests()
        self.f.setUp()
        self.conn = self.f.conn

    def tearDown(self):
        self.f.tearDown()

    def first_plan(self):
        self.f.apply_analysis()
        self.f.start('prepare_practice')
        self.f.bank_read()
        deliver(self.conn, self.f.root, self.f.data, self.f.plan(), self.f.lease)
        finish_task(self.conn, self.f.task['id'])
        return self.conn.execute('SELECT id FROM diagnostic_probes').fetchone()[0]

    def retained_plan(self, pid):
        value = self.f.plan()
        value['result']['exercises'] = []
        value['result']['retained_exercises'] = [{'probe_id': pid, 'goal_ids': ['region']}]
        return value

    def add_bank(self):
        path = self.f.data / 'next.png'
        Image.new('RGB', (30, 20), 'green').save(path)
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('bank-next','test','next','now')")
        self.conn.execute("INSERT INTO bank_resources VALUES('bank-next','{}','next.png',NULL,NULL)")
        init_access(self.conn)
        reveal(self.conn, 'bank-next', 'question', True)

    def read_next_bank(self):
        record_read(self.conn, self.f.lease, 'bank', 'bank-next', 'question',
                    resource_digest(self.f.data / 'next.png', self.f.data))

    def test_append_keeps_original_answer_exposure_and_current_goal_links(self):
        pid = self.first_plan()
        raw = BytesIO()
        Image.new('RGB', (200, 100), 'white').save(raw, format='PNG')
        image = save_answer_image(self.conn, self.f.data, raw.getvalue())
        aid = submit_probe(self.conn, pid, {'response': 'my endpoint calculation', 'answer_exposed': True,
                           'image_ids': [image['id']], 'image_roles': {image['id']: 'own_work'}})['attempt_id']
        before = dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?', (aid,)).fetchone())
        events = self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0]
        self.add_bank()
        self.f.start('prepare_practice')
        package = task_package(self.conn, self.f.task['id'])
        self.assertEqual(package['practice_mode'], 'append')
        self.assertEqual(package['required_retained_probe_ids'], [pid])
        self.read_next_bank()
        value = self.f.plan()
        value['result']['goals'].append({**value['result']['goals'][0], 'id': 'new-stage', 'question_numbers': [2]})
        value['result']['exercises'][0].update(bank_id='bank-next', goal_ids=['new-stage'])
        value['result']['retained_exercises'] = [{'probe_id': pid, 'goal_ids': ['region']}]
        saved = deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        self.assertTrue(deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)['reused'])
        finish_task(self.conn, self.f.task['id'])
        snap = loop_snapshot(self.conn)
        self.assertEqual(len(snap['goals']), 2)
        self.assertEqual(sum(p['is_current'] for p in snap['probes']), 2)
        self.assertEqual(snap['practice_states'][0]['last_added_count'], 1)
        self.assertEqual(snap['practice_states'][0]['last_retained_count'], 1)
        self.assertEqual(dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?', (aid,)).fetchone()), before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0], events)
        self.assertEqual(saved['projection']['retained'], 1)
        self.assertEqual(next(p for p in snap['probes'] if p['id'] == pid)['question_ids'],
                         [r[0] for r in self.conn.execute('SELECT id FROM questions ORDER BY id')])

    def test_no_new_candidate_preserves_existing_plan_and_does_not_duplicate_goals(self):
        pid = self.first_plan()
        for _ in range(2):
            self.f.start('prepare_practice')
            value = self.retained_plan(pid)
            value['result']['limitations'] = ['No additional verified candidate in the scope read.']
            deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
            finish_task(self.conn, self.f.task['id'])
        snap = loop_snapshot(self.conn)
        self.assertEqual(len(snap['probes']), 1)
        self.assertEqual(len(snap['goals']), 1)
        self.assertEqual(snap['practice_states'][0]['last_added_count'], 0)
        submit_probe(self.conn, pid, {'response': 'still belongs to this paper'})

    def test_omitted_existing_exercise_is_rejected_atomically(self):
        pid = self.first_plan()
        self.f.start('prepare_practice')
        before = self.conn.execute('SELECT count(*) FROM learning_results').fetchone()[0]
        value = self.retained_plan(pid)
        value['result']['retained_exercises'] = []
        with self.assertRaisesRegex(ValueError, '追加须保留'):
            deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_results').fetchone()[0], before)
        self.assertTrue(loop_snapshot(self.conn)['probes'][0]['is_current'])

    def test_repeat_reason_cannot_duplicate_a_pending_exercise(self):
        pid = self.first_plan()
        self.f.start('prepare_practice')
        self.f.bank_read()
        value = self.retained_plan(pid)
        value['result']['exercises'] = self.f.plan()['result']['exercises']
        value['result']['exercises'][0]['repeat_reason'] = 'another target'
        with self.assertRaisesRegex(ValueError, '同题|勿重复建题'):
            deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0], 1)

    def new_analysis(self):
        self.f.start()
        self.f.read_page()
        value = self.f.analysis()
        value['result']['report']['summary'] = 'Changed interpretation of the original work'
        deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        finish_task(self.conn, self.f.task['id'])

    def test_empty_plan_after_new_analysis_does_not_reactivate_unreviewed_exercises(self):
        pid = self.first_plan()
        self.new_analysis()
        self.f.start('prepare_practice')
        self.assertEqual(task_package(self.conn, self.f.task['id'])['practice_mode'], 'select')
        value = self.f.envelope({'goals': [], 'exercises': [], 'limitations': ['Previous exercise is not suitable.']})
        deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        finish_task(self.conn, self.f.task['id'])
        snap = loop_snapshot(self.conn)
        self.assertTrue(snap['practice_states'][0]['is_current'])
        self.assertFalse(snap['probes'][0]['is_current'])
        with self.assertRaisesRegex(ValueError, '已有作答保留'):
            submit_probe(self.conn, pid, {'response': 'cannot submit stale question'})

    def test_revalidated_old_question_requires_reading_and_preserves_identity(self):
        pid = self.first_plan()
        self.new_analysis()
        self.f.start('prepare_practice')
        value = self.retained_plan(pid)
        value['result']['goals'][0]['question_numbers'] = [2]
        with self.assertRaisesRegex(ValueError, '尚未读取'):
            deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        self.f.bank_read()
        deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        snap = loop_snapshot(self.conn)
        self.assertEqual([p['id'] for p in snap['probes'] if p['is_current']], [pid])
        self.assertEqual(snap['probes'][0]['question_ids'],
                         [self.conn.execute("SELECT id FROM questions WHERE number='2'").fetchone()[0]])

    def test_old_contract_is_readable_and_can_be_extended_without_migration_of_records(self):
        self.f.apply_analysis()
        with patch('app.learning.tasks.VERSION', '1.2'):
            self.f.start('prepare_practice')
        self.f.bank_read()
        value = self.f.plan()
        value['schema_version'] = '1.2'
        value['result'].pop('retained_exercises',None)
        deliver(self.conn, self.f.root, self.f.data, value, self.f.lease)
        finish_task(self.conn, self.f.task['id'])
        pid = self.conn.execute('SELECT id FROM diagnostic_probes').fetchone()[0]
        original = self.conn.execute('SELECT payload_json FROM diagnostic_probes').fetchone()[0]
        self.f.start('prepare_practice')
        deliver(self.conn, self.f.root, self.f.data, self.retained_plan(pid), self.f.lease)
        self.assertEqual(self.conn.execute('SELECT payload_json FROM diagnostic_probes').fetchone()[0], original)
        self.assertEqual(len(loop_snapshot(self.conn)['goals']), 1)

    def test_readable_blank_question_requires_topics_and_operations_but_not_guessed_causes(self):
        self.f.start()
        value = self.f.analysis()
        q = value['result']['report']['questions'][0]
        q['first_error'] = None
        q['answer_evidence'].update(student_work='', student_state='not_attempted', marking='none', marking_note='')
        q['skill_events'][0]['kind'] = 'incomplete'
        q['hypotheses'] = []
        validate_result(value, 'analyze_paper')
        for key in ('knowledge', 'methods', 'operations'):
            bad = copy.deepcopy(value)
            target = bad['result']['report']['questions'][0]
            (target if key == 'knowledge' else target['fingerprint'])[key] = []
            with self.assertRaisesRegex(ValueError, '结构不合法'):
                validate_result(bad, 'analyze_paper')
            bad['schema_version'] = '1.2'
            validate_result(bad, 'analyze_paper')

    def test_unreadable_material_can_keep_unknown_topics(self):
        self.f.start()
        value = self.f.analysis()
        q = value['result']['report']['questions'][0]
        q.update(knowledge=[], fingerprint={'conditions': [], 'goal': '', 'methods': [], 'operations': []},
                 correctness='unknown', evidence_status='missing', regions=[], first_error=None,
                 solution_guide=None, answer_evidence={'student_work':'', 'student_state':'unreadable',
                 'marking':'none', 'marking_note':''})
        value['result']['completion'] = 'needs_material'
        value['result']['report'].update(review={'status':'needs_review', 'issues':['Missing page region']},
                                         limitations=['Missing page region'])
        validate_result(value, 'analyze_paper')
