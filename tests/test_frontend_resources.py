"""Saved-resource APIs keep legacy clients and protected practice semantics."""
import json
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

import database_fixture as server
import test_learning_loop as fixtures
from app.config import AppConfig
from app.main import create_app
from app.bank.access import init_access, reveal
from app.learning.loop import submit_probe, assess_attempt


class FrontendResourceTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningLoopTests(); self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.f.apply()
        config = AppConfig(server.ROOT, server.DATA, server.DIST, server.DB_PATH)
        self.app = create_app(config, agent_factory=None)
        self.http = TestClient(self.app, base_url='http://127.0.0.1')
        self.addCleanup(self.app.state.runtime.close)
        self.addCleanup(self.http.close)
        self.conn = self.f.conn

    def test_paper_question_and_summary_reads_do_not_build_the_global_loop(self):
        with patch('app.services.workspace.loop_snapshot', side_effect=AssertionError('global loop')):
            self.assertIn('papers', self.http.get('/api/papers').json())
            papers = self.http.get('/api/papers?limit=1').json()
            self.assertEqual(papers['total'], 1)
            self.assertIsNone(papers['items'][0]['score'])
            detail = self.http.get('/api/papers/paper-test').json()
            self.assertEqual(detail['paper']['counts']['wrong'], 2)
            qs = self.http.get('/api/papers/paper-test/questions').json()['items']
            self.assertEqual([q['number'] for q in qs], ['1', '2'])
            self.assertIsNone(qs[0]['question_type']); self.assertIsNone(qs[0]['max_score'])
            q = self.http.get('/api/questions/'+qs[0]['id']).json()
            self.assertEqual(q['next_id'], qs[1]['id'])
            self.assertIsNone(q['previous_id']); self.assertFalse(q['capabilities']['step_comparison'])
            self.assertTrue(q['evidence_urls']); self.assertEqual(q['diagnosis']['correctness'], 'wrong')
            self.assertEqual(self.http.get('/api/papers/paper-test/summary').json()['status'], 'missing')

    def test_etag_304_and_personal_and_library_changes(self):
        path = '/api/papers?limit=1'
        before = self.http.get(path); tag = before.headers['etag']
        self.assertEqual(before.headers['cache-control'], 'private, no-cache')
        same = self.http.get(path, headers={'If-None-Match': '"unrelated", W/'+tag})
        self.assertEqual(same.status_code, 304); self.assertEqual(same.content, b'')
        self.assertEqual(self.http.post('/api/papers', json={'title': 'second'}).status_code, 201)
        changed = self.http.get(path, headers={'If-None-Match': tag})
        self.assertEqual(changed.status_code, 200); self.assertNotEqual(changed.headers['etag'], tag)
        old = self.http.get('/api/bank?limit=1')
        self.assertEqual(self.http.post('/api/bank/import', json={'questions': [{'id': 'new-bank', 'stem': 'new'}]}).status_code, 201)
        new = self.http.get('/api/bank?limit=1', headers={'If-None-Match': old.headers['etag']})
        self.assertEqual(new.status_code, 200); self.assertEqual(new.json()['total'], 2)
        self.assertEqual(self.http.get('/api/health').headers['cache-control'], 'no-store')

    def test_question_metadata_is_taken_from_unique_source_and_never_number_rules(self):
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('math1-2023-01','S01','q','now')")
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)', ('math1-2023-01', json.dumps({'question_type': '选择题', 'score': 5}), 'unused.png', None, None))
        init_access(self.conn)
        self.conn.execute("UPDATE papers SET title='2023 数学一',source_name='2023 数学一.pdf' WHERE id='paper-test'")
        self.conn.commit()
        qs = self.http.get('/api/papers/paper-test/questions').json()['items']
        self.assertEqual(qs[0]['matched_bank_id'], 'math1-2023-01')
        self.assertEqual(qs[0]['question_type'], '选择题'); self.assertEqual(qs[0]['max_score'], 5)
        self.assertIsNone(qs[1]['question_type']); self.assertIsNone(qs[1]['max_score'])
        self.conn.execute("UPDATE papers SET source_name='2022 数学一.pdf' WHERE id='paper-test'"); self.conn.commit()
        self.assertIsNone(self.http.get('/api/papers/paper-test/questions').json()['items'][0]['matched_bank_id'])

    def test_s01_numeric_source_types_are_decoded_without_guessing_other_sources(self):
        from app.services.frontend_reads import metadata
        for code,label in ((1,'选择题'),(2,'填空题'),(3,'解答题'),(99,None)):
            value={'type':code,'score':5,'source_url':'https://github.com/lx-ruc/kaoyanshuxue'}
            self.conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(json.dumps(value),'bank-test'))
            self.assertEqual(metadata(self.conn,'bank-test'),{'question_type':label,'max_score':5})
        self.conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(json.dumps({'type':1,'score':5}),'bank-test'))
        self.assertIsNone(metadata(self.conn,'bank-test')['question_type'])
        self.conn.rollback()

    def test_standard_text_source_matches_paper_and_practice_with_masking(self):
        from test_source_import import question
        from app.bank.source_records import canonical,bank_id
        from app.bank.source_import import import_source
        value=question(); bid=bank_id(value)
        path=self.f.root/'standard.jsonl';path.write_text(canonical(value),encoding='utf8')
        config=self.app.state.runtime.config
        plan=import_source(config,'S02',path)
        import_source(config,'S02',path,confirm=plan['plan_sha256'])
        self.conn.execute("UPDATE papers SET title='2026 数学一',source_name='2026 数学一.pdf' WHERE id='paper-test'")
        self.conn.execute("UPDATE diagnostic_probes SET bank_id=?",(bid,));self.conn.commit()
        card=self.http.get('/api/papers/paper-test/questions').json()['items'][0]
        self.assertEqual((card['matched_bank_id'],card['question_type'],card['max_score']),(bid,'选择题',5))
        practice='/api/practices/paper-test-probe-test'
        self.assertIsNone(self.http.get(practice).json()['question'])
        reveal(self.conn,bid,'question',True);self.conn.commit()
        visible=self.http.get(practice).json()['question']
        self.assertIn('A. $2$',visible['question_text'])
        self.assertNotIn('question_image',visible)
        reveal(self.conn,bid,'analysis',True);self.conn.commit()
        self.assertNotIn('analysis_text',self.http.get(practice).json()['question'])
        submit_probe(self.conn,'paper-test-probe-test',{'response':'independent steps'});self.conn.commit()
        self.assertEqual(self.http.get(practice).json()['question']['analysis_text'],'$1+1=2$')

    def test_practice_mask_reveal_submission_analysis_and_history(self):
        self.conn.execute("UPDATE bank_identity SET math_type=1,year='2023' WHERE bank_id='bank-test'")
        self.conn.execute("DELETE FROM bank_views WHERE bank_id='bank-test'"); self.conn.commit()
        pid = 'paper-test-probe-test'; path = '/api/practices/'+pid
        hidden = self.http.get(path).json()
        self.assertIsNone(hidden['question']); self.assertEqual(hidden['actions'], ['reveal_question'])
        reveal(self.conn, 'bank-test', 'question', True); self.conn.commit()
        visible = self.http.get(path).json()
        self.assertIn('question_image', visible['question']); self.assertNotIn('expected', visible['question'])
        reveal(self.conn, 'bank-test', 'analysis', True); self.conn.commit()
        self.assertNotIn('analysis_image', self.http.get(path).json()['question'])
        aid = submit_probe(self.conn, pid, {'response': 'my own steps'})['attempt_id']; self.conn.commit()
        submitted = self.http.get(path).json()
        self.assertEqual(submitted['practice']['status'], 'grading')
        self.assertEqual(submitted['question']['expected'], '2/3')
        assess_attempt(self.conn, aid, {'correct': True, 'feedback': 'verified', 'author': 'test'}); self.conn.commit()
        graded = self.http.get(path).json()
        self.assertEqual(graded['practice']['status'], 'graded')
        history = self.http.get(path+'/attempts?limit=1').json()
        self.assertEqual(history['total'], 1); self.assertTrue(history['items'][0]['answer_exposed'])
        self.assertNotIn('expected', history['items'][0])
        groups = self.http.get('/api/practices?group_by=paper&limit=1').json()
        self.assertEqual(groups['counts']['graded'], 1)
        self.assertEqual(groups['items'][0]['id'], 'paper-test')

    def test_archived_practice_has_history_but_no_material_or_submission_action(self):
        self.assertEqual(self.http.post('/api/papers/paper-test/archive', json={'confirmed': True}).status_code, 200)
        value = self.http.get('/api/practices/paper-test-probe-test').json()
        self.assertEqual(value['practice']['status'], 'inactive')
        self.assertIsNone(value['question']); self.assertEqual(value['actions'], [])
        self.assertEqual(self.http.get('/api/practices').json()['total'], 0)
        self.assertEqual(self.http.get('/api/practices?include_inactive=true').json()['total'], 1)

    def test_missing_invalid_and_conditional_requests_keep_their_errors(self):
        for path in ('/api/papers/missing', '/api/papers/missing/questions', '/api/papers/missing/summary',
                     '/api/questions/missing', '/api/practices/missing', '/api/practices/missing/attempts', '/api/knowledge/topics/missing'):
            self.assertEqual(self.http.get(path, headers={'If-None-Match': '*'}).status_code, 404, path)
        for path in ('/api/papers?limit=0', '/api/bank?limit=101', '/api/practices?offset=-1', '/api/practices?status=bad', '/api/practices?group_by=bad', '/api/bank?limit=1&math_type=4'):
            self.assertEqual(self.http.get(path).status_code, 400, path)


class FrozenFrontendTests(unittest.TestCase):
    def test_new_detail_keeps_frozen_resource_urls(self):
        from test_frozen_practice import FrozenPracticeTests
        f = FrozenPracticeTests(); f.setUp(); self.addCleanup(f.doCleanups)
        config = f.service.config
        app = create_app(config, agent_factory=None)
        self.addCleanup(app.state.runtime.close)
        http = TestClient(app, base_url='http://127.0.0.1'); self.addCleanup(http.close)
        value = http.get('/api/practices/'+f.probe_id).json()
        if value['question'] is None:
            reveal(f.conn, value['practice']['bank_id'], 'question', True); f.conn.commit()
            value = http.get('/api/practices/'+f.probe_id).json()
        url = value['question'].get('question_image')
        if url:self.assertIn('probe_id='+f.probe_id, url)
        else:self.assertIn('question_text', value['question'])

    def test_deferred_detail_keeps_attempts_and_withholds_current_bank_material(self):
        from test_deferred_practice import DeferredPracticeTests
        f=DeferredPracticeTests();f.setUp();self.addCleanup(f.doCleanups)
        f.remove_proof();f.save_without_unsafe_old_exercise()
        app=create_app(AppConfig(server.ROOT,server.DATA,server.DIST,server.DB_PATH),agent_factory=None)
        self.addCleanup(app.state.runtime.close)
        http=TestClient(app,base_url='http://127.0.0.1');self.addCleanup(http.close)
        value=http.get('/api/practices/'+f.pid).json()
        self.assertEqual(value['practice']['status'],'inactive')
        self.assertIsNone(value['question']);self.assertEqual(value['actions'],[])
        self.assertTrue(value['review_reason'])
        self.assertEqual(value['latest_attempt']['response'],f.base.original['response'])
        self.assertEqual(http.get('/api/practices/'+f.pid+'/attempts').json()['total'],1)

    def test_topic_detail_and_bank_topic_pagination_use_verified_links(self):
        from test_question_annotations import QuestionPreparationTests
        f=QuestionPreparationTests();f.setUp();self.addCleanup(f.tearDown)
        ids=f.save_annotation()
        app=create_app(f.f.config,agent_factory=None)
        self.addCleanup(app.state.runtime.close)
        http=TestClient(app,base_url='http://127.0.0.1');self.addCleanup(http.close)
        result=http.get('/api/bank?topic_id=GS-04-001&limit=1')
        self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(result.json()['total'],len(ids))
        self.assertEqual(len(result.json()['items']),1)
        value=http.get('/api/knowledge/topics/GS-04-001')
        self.assertEqual(value.status_code,200,value.text)
        self.assertEqual(value.json()['topic']['id'],'GS-04-001')
        self.assertTrue(value.json()['topic']['definition'])
        self.assertEqual(value.json()['question_counts']['bank'],1)  # aliases grouped
        self.assertEqual(http.get('/api/bank?topic_id=missing&limit=1').status_code,400)
