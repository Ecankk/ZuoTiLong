"""Prepared recall uses real annotations, history and HTTP boundaries in isolated data."""
import copy
import hashlib
import json
import unittest
import uuid

from fastapi.testclient import TestClient
from app.agent.tools import execute
from app.bank import annotations
from app.bank.access import save_preferences, record_view
from app.bank.retrieval import recall
from app.knowledge import catalog
from app.main import create_app

TOPIC = 'GS-04-001'
PARENT = 'math1.calculus.differentiation'


class BankRetrievalTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f = QuestionPreparationTests()
        self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.ids = self.f.save_annotation()
        self.conn, self.data = self.f.conn, self.f.data
        self.root, self.config = self.f.root, self.f.f.config

    def query(self, **kwargs):
        return recall(self.conn, self.data, topic_ids=kwargs.pop('topic_ids', [TOPIC]), **kwargs)

    def tool(self, payload):
        return json.loads(execute(self.root, self.data, 'catalog', payload)[0]['text'])

    def counts(self):
        return {name: self.conn.execute('SELECT count(*) FROM ' + name).fetchone()[0]
                for name in ('diagnostic_probes', 'probe_attempts', 'learning_events', 'bank_views', 'bank_exposures')}

    def ready_question(self, bid, status='ready', *, shift=None):
        from app.bank.access import init_access
        from app.learning.tasks import finish_task
        if shift is None:
            shift = self.conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0]
        self.conn.execute('''INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at)
            VALUES(?,?,?,?,?,'now')''', (bid, 'synthetic', f'求sin(x²+{shift})的导数',
                f'2x cos(x²+{shift})', '外层求导并乘内层导数2x。'))
        init_access(self.conn)
        self.conn.commit()
        if status == 'unannotated':
            return bid
        self.f.start('annotate_questions', {'bank_ids': [bid]})
        self.f.read_annotation_material()
        result = self.f.annotation_result(status)
        item = result['questions'][0]
        item['reference_reasoning'] = f'设u=x²+{shift}，对sin(u)使用链式法则，得到2x cos(x²+{shift})。'
        item['fingerprint']['conditions'] = [f'sin(x²+{shift})']
        self.f.tool('apply_report', {'result': self.f.envelope(result)})
        finish_task(self.conn, self.f.task['id'])
        self.conn.commit()
        return bid

    def probe(self, bid=None, *, correct='unanswered'):
        """Seed saved historical projections; this does not test result delivery."""
        bid = bid or self.ids[0]
        suffix = uuid.uuid4().hex
        paper, question, report, task, result, probe = (prefix + suffix for prefix in ('p-', 'q-', 'r-', 't-', 'res-', 'probe-'))
        self.conn.execute("INSERT INTO papers(id,title,created_at) VALUES(?,'synthetic earlier paper','now')", (paper,))
        self.conn.execute("INSERT INTO questions(id,paper_id,number,created_at) VALUES(?,?,'1','now')", (question, paper))
        self.conn.execute("INSERT INTO agent_reports VALUES(?,?,'source','{}','now')", (report, paper))
        source = dict(self.conn.execute('SELECT * FROM learning_tasks ORDER BY rowid DESC LIMIT 1').fetchone())
        source.update(id=task, request_id=suffix, workflow_id=task, paper_id=paper, kind='prepare_practice',
                      input_json=json.dumps({'reports': [{'id': report}]}), result_id=result, status='completed')
        columns = ','.join(source)
        self.conn.execute(f'INSERT INTO learning_tasks({columns}) VALUES({",".join("?" for _ in source)})', tuple(source.values()))
        payload = json.dumps({'schema_version': '1.6', 'result': {'exercises': []}})
        self.conn.execute('INSERT INTO learning_results VALUES(?,?,?,?,?,?,?)',
                          (result, task, paper, 'prepare_practice', hashlib.sha256(payload.encode()).hexdigest(), payload, 'now'))
        self.conn.execute('INSERT INTO diagnostic_probes VALUES(?,?,?,?,?,?,?,?)',
                          (probe, paper, question, bid, TOPIC, '{"prompt":"PRIVATE_PROMPT"}', 'awaiting_response', 'now'))
        self.conn.execute('INSERT INTO practice_plan_members VALUES(?,?)', (result, probe))
        if correct != 'unanswered':
            self.attempt(probe, correct)
        self.conn.commit()
        return probe, paper, task

    def attempt(self, pid, correct, attempt_id=None):
        assessment = None if correct == 'ungraded' else json.dumps({'correct': correct, 'feedback': 'PRIVATE_FEEDBACK'})
        self.conn.execute('''INSERT INTO probe_attempts(id,probe_id,response,assessment_json,created_at)
                             VALUES(?,?,'PRIVATE_STUDENT_WORK',?,'2026-01-01')''',
                          (attempt_id or uuid.uuid4().hex, pid, assessment))

    def test_subtree_stage_method_and_stable_representative_have_no_category_priority(self):
        expected = min(self.ids, key=lambda bid: hashlib.sha256(bid.encode()).digest())
        result = self.query(topic_ids=[PARENT], stages=['formula'], methods=['链式求导'], internal=True)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], expected)
        self.assertEqual(set(result['items'][0]['aliases']), set(self.ids))
        self.assertEqual(self.query(stages=['modeling'])['total'], 0)
        self.assertEqual(self.query(methods=['分部积分'])['total'], 0)

    def test_all_categories_share_pool_and_legacy_filter_is_ignored(self):
        for category in (1, 2, 3):
            self.ready_question(f'math{category}-2018-03')
        result = self.tool({'topic_ids': [TOPIC], 'math_types': [1]})
        self.assertEqual(result['total'], 4)
        self.assertEqual({row['math_type'] for row in result['items']}, {1, 2, 3})
        self.assertIn('已忽略', result['scope_note'])

    def test_confirmed_alias_representative_can_be_math_two(self):
        first_hash = min(hashlib.sha256(bid.encode()).digest() for bid in self.ids)
        bid = next(f'math2-2017-{n:02}' for n in range(1, 99)
                   if hashlib.sha256(f'math2-2017-{n:02}'.encode()).digest() < first_hash)
        self.ready_question(bid, shift=0)
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)', (self.ids[0], bid, 'sin(x²+0) is identical to sin(x²).'))
        result = self.query()
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], bid)
        self.assertEqual(result['items'][0]['math_type'], 2)

    def test_unreviewed_and_unannotated_materials_never_enter_prepared_pool(self):
        for number, status in enumerate(('needs_catalog', 'needs_review', 'unannotated'), 2):
            self.ready_question(f'math3-2018-{number:02}', status)
        self.assertEqual(self.query()['total'], 1)

    def test_alias_link_confirmed_after_two_annotations_still_returns_one_question(self):
        bid = self.ready_question('math3-2018-02')
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)', (self.ids[0], bid, 'synthetic confirmed same question'))
        self.conn.commit()
        result = self.query(internal=True)
        self.assertEqual(result['total'], 1)
        self.assertEqual(set(result['items'][0]['aliases']), {*self.ids, bid})

    def test_any_confirmed_alias_reserved_excludes_whole_group(self):
        representative = self.query()['items'][0]['id']
        other = next(bid for bid in self.ids if bid != representative)
        identity = self.conn.execute('SELECT * FROM bank_identity WHERE bank_id=?', (other,)).fetchone()
        save_preferences(self.conn, {'study_type': 1, 'reserved': [{'math_type': identity['math_type'], 'year': identity['year']}]})
        self.assertEqual(self.query()['total'], 0)
        self.assertEqual(self.query()['existing_exercises'], [])

    def test_changed_definition_invalidates_ready_but_keeps_original_annotation(self):
        value = copy.deepcopy(catalog.document(self.conn)['document'])
        atom = next(n for n in value['nodes'] if n['id'] == TOPIC)
        atom['conditions'].append('新审定的适用条件。')
        self.f.f.publish(value)
        self.conn.commit()
        self.assertEqual(self.query()['total'], 0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0], 1)

    def test_unrelated_catalog_change_keeps_ready_usable(self):
        value = copy.deepcopy(catalog.document(self.conn)['document'])
        unrelated = next(n for n in value['nodes'] if n['id'] == 'math1.probability')
        unrelated['review_note'] = 'unrelated note'
        self.f.f.publish(value)
        self.conn.commit()
        self.assertEqual(self.query()['total'], 1)

    def test_subtree_expansion_is_not_truncated_to_catalog_navigation_page(self):
        value = copy.deepcopy(catalog.document(self.conn)['document'])
        for number in range(110):
            value['nodes'].append({'id': f'A-{number:03}', 'parent_id': PARENT,
                'name': f'隔离目录分支{number}', 'kind': 'topic', 'definition': 'Synthetic navigation branch.',
                'conditions': [], 'boundaries': [], 'aliases': [], 'math_types': [1, 2, 3],
                'source_refs': [], 'review_note': 'Isolated pagination fixture.'})
        self.f.f.publish(value)
        first_page = catalog.search(self.conn, parent_id=PARENT, limit=100)
        self.assertNotIn(TOPIC, {n['id'] for n in first_page['items']})
        self.assertEqual(self.query(topic_ids=[PARENT])['total'], 1)

    def test_confirmed_id_redirect_recalls_old_annotations_without_rewriting_history(self):
        value = copy.deepcopy(catalog.document(self.conn)['document'])
        atom = next(n for n in value['nodes'] if n['id'] == TOPIC)
        atom['id'] = 'project.chain-rule'
        value['redirects'].append({'old_id': TOPIC, 'target_id': atom['id'], 'reason': 'Same definition and conditions.'})
        for resolution in value['source_resolutions']:
            resolution['node_ids'] = [atom['id'] if tid == TOPIC else tid for tid in resolution['node_ids']]
        self.f.f.publish(value)
        self.assertEqual(self.query(topic_ids=['project.chain-rule'])['total'], 1)
        self.assertEqual(self.query()['total'], 1)
        original = json.loads(self.conn.execute('SELECT payload_json FROM question_annotations').fetchone()[0])
        self.assertEqual(original['bindings'][0]['topic_id'], TOPIC)

    def test_pending_alias_reuses_original_probe_identity_without_writes(self):
        representative = self.query()['items'][0]['id']
        other = next(bid for bid in self.ids if bid != representative)
        pid, _, _ = self.probe(other)
        before = self.counts()
        result = self.query()
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['omitted']['pending_existing'], 1)
        existing = result['existing_exercises'][0]
        self.assertEqual(existing['probe_id'], pid)
        self.assertEqual(existing['id'], other)
        self.assertEqual(existing['bank_id'], other)
        self.assertEqual(existing['student_access']['id'], other)
        self.assertTrue(existing['can_reuse'])
        self.assertEqual(before, self.counts())

    def test_ungraded_or_material_needed_never_becomes_duplicate_assignment(self):
        for correct, status in (('ungraded', 'awaiting_grading'), (None, 'needs_material')):
            with self.subTest(correct=correct):
                pid, paper, _ = self.probe(correct=correct)
                result = self.query(include_history=True)
                row = next(r for r in result['existing_exercises'] if r['probe_id'] == pid)
                self.assertEqual(row['status'], status)
                self.assertEqual(result['total'], 0)
                self.conn.execute('UPDATE papers SET archived_at=? WHERE id=?', ('now', paper))

    def test_latest_attempt_uses_insertion_order_when_timestamp_is_tied(self):
        pid, _, _ = self.probe()
        self.attempt(pid, None, 'z-old')
        self.attempt(pid, True, 'a-new')
        result = self.query(include_history=True)
        existing = next(r for r in result['existing_exercises'] if r['probe_id'] == pid)
        self.assertEqual(existing['status'], 'reviewed')
        self.assertEqual(result['total'], 1)

    def test_stale_pending_plan_points_to_original_but_cannot_be_reused_or_copied(self):
        pid, _, task = self.probe()
        self.conn.execute("UPDATE learning_tasks SET input_json='{\"reports\":[]}' WHERE id=?", (task,))
        result = self.query()
        self.assertEqual(result['total'], 0)
        self.assertEqual(result['existing_exercises'][0]['probe_id'], pid)
        self.assertFalse(result['existing_exercises'][0]['can_reuse'])

    def test_archived_or_retired_unanswered_exercise_does_not_block_fresh_candidate(self):
        for state in ('archived', 'retired'):
            with self.subTest(state=state):
                pid, paper, _ = self.probe()
                if state == 'archived':
                    self.conn.execute("UPDATE papers SET archived_at='now' WHERE id=?", (paper,))
                else:
                    self.conn.execute("INSERT INTO retired_probes VALUES(?,'synthetic retired','now')", (pid,))
                result = self.query()
                self.assertEqual(result['total'], 1)
                self.assertEqual(result['existing_exercises'], [])

    def test_reviewed_history_requires_explicit_review_search(self):
        for correct in (True, False):
            with self.subTest(correct=correct):
                _, paper, _ = self.probe(correct=correct)
                self.assertEqual(self.query()['total'], 0)
                review = self.query(include_history=True, internal=True)
                self.assertEqual(review['total'], 1)
                self.assertGreaterEqual(review['items'][0]['history']['attempt_count'], 1)
                self.conn.execute("UPDATE papers SET archived_at='now' WHERE id=?", (paper,))

    def test_seeing_question_is_not_solution_exposure_or_learning_success(self):
        before = self.counts()
        record_view(self.conn, self.ids[0], 'question')
        self.assertEqual(self.query()['total'], 1)
        item = self.query()['items'][0]
        self.assertTrue(item['history']['seen_question'])
        self.assertFalse(item['history']['seen_solution'])
        self.assertEqual(self.counts()['learning_events'], before['learning_events'])
        record_view(self.conn, self.ids[1], 'answer')
        self.assertEqual(self.query()['total'], 0)
        self.assertEqual(self.query(include_history=True)['total'], 1)

    def test_history_filtering_precedes_pagination(self):
        for category in (2, 3):
            self.ready_question(f'math{category}-2018-04')
        ordered = self.query()['items']
        for item in ordered[:2]:
            record_view(self.conn, item['id'], 'analysis')
        result = self.query(limit=1)
        self.assertEqual(result['total'], 1)
        self.assertEqual(result['items'][0]['id'], ordered[-1]['id'])
        self.assertIsNone(result['next_offset'])

    def test_recall_preserves_outer_transaction_and_does_not_create_read_receipts(self):
        before = self.counts()
        reads = self.conn.execute('SELECT count(*) FROM task_reads').fetchone()[0]
        save_preferences(self.conn, {'study_type': 1, 'mask_same_type': False})
        changes = self.conn.total_changes
        self.assertTrue(self.conn.in_transaction)
        self.assertTrue(self.query()['items'][0]['student_access']['can_view'])
        self.assertTrue(self.conn.in_transaction)
        self.assertEqual(self.conn.total_changes, changes)
        self.conn.rollback()
        self.assertFalse(self.query()['items'][0]['student_access']['can_view'])
        self.assertEqual(before, self.counts())
        self.assertEqual(reads, self.conn.execute('SELECT count(*) FROM task_reads').fetchone()[0])

    def test_tool_keeps_source_navigation_and_rejects_mixed_queries(self):
        prepared = self.tool({'topic_ids': [TOPIC]})
        self.assertEqual(prepared['retrieval_mode'], 'prepared_atoms')
        self.assertIn('bindings', prepared['items'][0])
        self.assertEqual(self.tool({'limit': 1})['retrieval_mode'], 'source_navigation')
        with self.assertRaisesRegex(ValueError, '分别调用'):
            self.tool({'topic_ids': [TOPIC], 'topics': ['求导']})

    def test_bad_query_types_and_unknown_id_fail_before_returning_candidates(self):
        bad = ({'topic_ids': []}, {'topic_ids': ['unknown']}, {'topic_ids': [True]},
               {'limit': True}, {'offset': -1}, {'methods': '链式求导'}, {'stages': ['invented']},
               {'include_history': 'yes'})
        for args in bad:
            with self.subTest(args=args), self.assertRaises(ValueError):
                self.query(**args)

    def test_http_returns_only_metadata_even_when_candidate_or_probe_is_hidden(self):
        pid, _, _ = self.probe()
        self.conn.commit()
        before = self.counts()
        with TestClient(create_app(self.config, agent_factory=None), base_url='http://127.0.0.1') as http:
            response = http.get('/api/bank/search', params={'topic_id': TOPIC})
            self.assertEqual(response.status_code, 200, response.text)
            body = response.json()
            self.assertEqual(body['existing_exercises'][0]['probe_id'], pid)
            self.assertEqual(body['items'], [])
            self.assertEqual(http.get('/api/bank/search', params={'topic_id': 'unknown'}).status_code, 400)
            self.assertEqual(http.get('/api/bank/search').status_code, 400)
            self.assertEqual(http.get('/api/bank/search', params={'topic_id': TOPIC, 'limit': 101}).status_code, 400)
        forbidden = ('PRIVATE_', 'sin(', 'cos(', 'reference_reasoning', 'fingerprint', 'checkpoints', 'bindings', 'question_path')
        text = json.dumps(body, ensure_ascii=False)
        for token in forbidden:
            self.assertNotIn(token, text)
        self.assertEqual(before, self.counts())

    def test_http_candidate_metadata_never_includes_content_even_after_visibility_changes(self):
        for masked in (True, False):
            with self.subTest(masked=masked):
                save_preferences(self.conn, {'study_type': 1, 'mask_same_type': masked})
                self.conn.commit()
                before = self.counts()
                with TestClient(create_app(self.config, agent_factory=None), base_url='http://127.0.0.1') as http:
                    response = http.get('/api/bank/search', params={'topic_id': TOPIC})
                    self.assertEqual(response.status_code, 200, response.text)
                    item = response.json()['items'][0]
                    self.assertEqual(item['student_access']['can_view'], not masked)
                    for key in ('stem', 'answer', 'explanation', 'bindings', 'fingerprint', 'methods',
                                'checkpoints', 'reference_reasoning', 'question_path', 'analysis_path'):
                        self.assertNotIn(key, item)
                self.assertEqual(before, self.counts())


if __name__ == '__main__':
    unittest.main()
