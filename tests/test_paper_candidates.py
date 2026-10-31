import copy
import json
import unittest
from unittest.mock import patch

import test_learning_loop as fixtures
from app.bank import paper_candidates
from app.bank.access import init_access, save_preferences
from app.agent.tools import execute


class PaperCandidateTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningLoopTests()
        self.fixture.setUp()
        self.conn = self.fixture.conn
        for category in (1, 2, 3):
            for number in (1, 2, 99):
                bid = f'math{category}-2023-{number:02d}'
                self.conn.execute('INSERT INTO bank_questions(id,source,stem,created_at) VALUES(?,?,?,?)', (bid, 'test', 'SECRET STEM', 'now'))
                self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)', (bid, '{}', 'unused.png', None, None))
        init_access(self.conn)
        self.conn.execute("UPDATE papers SET title='2023年数一',source_name='2023数学(一).pdf',source_sha256=? WHERE id='paper-test'", (self.fixture.digest,))
        self.fixture.apply()

    def tearDown(self):
        self.fixture.tearDown()

    def paper(self):
        return dict(self.conn.execute("SELECT * FROM papers WHERE id='paper-test'").fetchone())

    def test_exact_source_navigation_is_read_only_without_exposing_content_or_asserting_ready(self):
        before = self.conn.total_changes
        result = paper_candidates.locate(self.conn, self.paper())
        self.assertEqual([g['sources'][0]['bank_id'] for g in result['candidates']], ['math1-2023-01', 'math1-2023-02'])
        self.assertTrue(result['navigation_only'])
        for word in ('SECRET STEM', 'reference_reasoning', 'ready', 'source_sha256'):
            self.assertNotIn(word, json.dumps(result))
        self.assertEqual(self.conn.total_changes, before)

    def test_exam_date_and_study_preference_do_not_define_source(self):
        paper = {**self.paper(), 'title': '完成卷', 'source_name': 'scan.pdf', 'exam_date': '2023-01-01'}
        self.assertEqual(paper_candidates.locate(self.conn, paper)['locator']['status'], 'missing_year')
        paper['title'] = '2023试卷'
        result = paper_candidates.locate(self.conn, paper)
        self.assertIsNone(result['locator']['math_type'])
        self.assertEqual(len(result['candidates'][0]['sources']), 3)

    def test_conflicting_year_or_category_does_not_pick_a_candidate(self):
        for edit in ({'source_name': '2022数一.pdf'}, {'math_type': 2}, {'title': '2023数一、数二'}):
            result = paper_candidates.locate(self.conn, {**self.paper(), **edit})
            self.assertEqual(result['locator']['status'], 'ambiguous')
            self.assertEqual(result['candidates'], [])

    def test_uncovered_year_is_not_substituted_by_nearest_year(self):
        result = paper_candidates.locate(self.conn, {**self.paper(), 'title': '2026数一', 'source_name': '2026数一.pdf'})
        self.assertEqual(result['candidates'], [])
        self.assertEqual(result['not_located_numbers'], [1, 2])

    def test_current_report_excludes_stale_extraction_numbers(self):
        self.conn.execute("INSERT INTO questions(id,paper_id,number,created_at) VALUES('stale','paper-test',99,'now')")
        self.assertEqual(paper_candidates.question_numbers(self.conn, self.paper()), [1, 2])
        self.assertEqual(paper_candidates.question_numbers(self.conn, {**self.paper(), 'source_sha256': 'changed'}), [1, 2, 99])

    def test_single_question_scope_does_not_return_rest_of_paper(self):
        result = paper_candidates.locate(self.conn, self.paper(), selected_number=2)
        self.assertEqual([g['number'] for g in result['candidates']], [2])
        self.assertEqual(paper_candidates.locate(self.conn, self.paper(), selected_number=True)['candidates'], [])

    def test_reserved_source_remains_excluded_but_masking_does_not_hide_internal_locator(self):
        self.assertTrue(paper_candidates.locate(self.conn, self.paper())['candidates'])
        save_preferences(self.conn, {'study_type': 1, 'reserved': [{'math_type': 1, 'year': '2023'}]})
        self.assertEqual(paper_candidates.locate(self.conn, self.paper())['candidates'], [])

    def test_chinese_and_numeric_filename_variations(self):
        for name, category in [('2023数学（一）.pdf', 1), ('2023数学(二.pdf', 2), ('2023 数学 3.pdf', 3), ('2023数二.pdf', 2)]:
            result = paper_candidates.location({'source_name': name})
            self.assertEqual((result['year'], result['math_type']), ('2023', category))
        self.assertIsNone(paper_candidates.location({'title': '20231数学12'})['year'])

    def test_read_paper_tool_actually_returns_locator_with_original_page(self):
        with patch('app.agent.tools.connection', lambda data: fixtures.server.connect()):
            result = execute(fixtures.ROOT, self.fixture.root, 'read_paper', {'paper_id': 'paper-test', 'pages': [1]})
        text = next(item['text'] for item in result if item['type'] == 'text')
        value = json.loads(text)
        self.assertEqual(value['bank_locator_candidates']['candidates'][0]['sources'][0]['bank_id'], 'math1-2023-01')
        self.assertTrue(any(item['type'] == 'image' for item in result))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM probe_attempts').fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
