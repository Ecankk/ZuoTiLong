import copy
import unittest
from unittest.mock import patch

import test_learning_loop as fixtures
from app.config import AppConfig
from app.learning.loop import apply_report
from app.services.papers import PaperService
from app.storage.database import Database


class QuestionIdCollisionTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningLoopTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.conn = self.f.conn
        self.original = {'1': 'paper-test-q-01', '3': 'paper-test-q-02', '4': 'paper-test-q-03'}
        for number, qid in self.original.items():
            self.conn.execute('INSERT INTO questions(id,paper_id,number,stem,created_at) VALUES(?,?,?,?,?)',
                              (qid, 'paper-test', number, 'Extracted question '+number, 'now'))
        self.conn.commit()

    def assert_completed_numbers(self):
        actual = {r['number']: r['id'] for r in self.conn.execute('SELECT id,number FROM questions WHERE paper_id=?', ('paper-test',))}
        self.assertEqual(set(actual), {'1', '2', '3', '4'})
        self.assertEqual({n: actual[n] for n in self.original}, self.original)
        self.assertNotIn(actual['2'], self.original.values())
        return actual

    def test_report_inserts_missing_middle_number_without_changing_existing_ids(self):
        report = copy.deepcopy(self.f.report)
        report['expected_count'] = 4
        report['probes'] = []
        report['questions'] = [dict(copy.deepcopy(report['questions'][0]), number=n) for n in range(1, 5)]
        saved = apply_report(self.conn, 'paper-test', report, fixtures.ROOT)
        before = self.assert_completed_numbers()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_diagnoses').fetchone()[0], 4)
        again = apply_report(self.conn, 'paper-test', report, fixtures.ROOT)
        self.assertEqual(saved['report_id'], again['report_id'])
        self.assertEqual(before, self.assert_completed_numbers())

    def test_reextraction_inserts_missing_middle_number_without_id_collision(self):
        config = AppConfig(fixtures.ROOT, self.f.root, self.f.root/'dist', fixtures.server.DB_PATH)
        service = PaperService(config, Database(config))
        result = dict(questions=[dict(number=str(n), stem='Question '+str(n), regions=[]) for n in range(1, 5)],
                      pages=[{}], engine='synthetic', message='complete', warnings=[], complete=True,
                      source_sha256=self.f.digest)
        with patch('app.services.papers.extract_pdf', return_value=result):
            service.analyze(self.conn, 'paper-test')
            before = self.assert_completed_numbers()
            service.analyze(self.conn, 'paper-test')
            self.assertEqual(before, self.assert_completed_numbers())
