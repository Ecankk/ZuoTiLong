import json,uuid,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import test_learning_loop as fixtures
import database_fixture as server
from app.config import AppConfig
from app.main import create_app
from app.services.papers import PaperService
from app.storage.database import Database
from app.storage.path_upgrade import status
from app.learning.student_text import validate_student_text


class F5BackendTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LearningLoopTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.config=AppConfig(server.ROOT,server.DATA,server.DIST,server.DB_PATH)
        self.service=PaperService(self.config,Database(self.config))

    def client(self):
        app=create_app(self.config,agent_factory=None);self.addCleanup(app.state.runtime.close)
        http=TestClient(app,base_url='http://127.0.0.1');self.addCleanup(http.close)
        return app,http

    def test_status_never_runs_full_inventory_or_reads_file_bytes(self):
        with patch('app.storage.path_upgrade.preview',side_effect=AssertionError('preview')), \
             patch('app.storage.path_upgrade.inventory',side_effect=AssertionError('inventory')), \
             patch.object(Path,'read_bytes',side_effect=AssertionError('file hash')):
            value=status(self.config)
        self.assertIn('path_migration',value)

    def test_student_prose_rejects_internal_roles_nested(self):
        for text in ('你的附件是 own_work','请补 external_solution','附件 marking 不算独立步骤'):
            with self.assertRaises(ValueError):validate_student_text({'observations':[{'evidence':text}]})
        validate_student_text({'feedback':'请补拍你的作答，参考解析不能作为独立作答。'})

    def test_internal_role_rejection_does_not_save_feedback(self):
        from app.learning.loop import submit_probe,assess_attempt
        self.f.apply()
        aid=submit_probe(self.f.conn,'paper-test-probe-test',{'response':'my own steps'})['attempt_id']
        with self.assertRaisesRegex(ValueError,'内部附件角色名'):
            assess_attempt(self.f.conn,aid,{'author':'fixture','correct':None,'feedback':'请上传 own_work'})
        self.assertIsNone(self.f.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0])

    def test_preparation_returns_only_task_summary_and_validates_uuid(self):
        app,http=self.client()
        with patch.object(app.state.runtime.agent,'invoke',return_value={'session_id':'secret','messages':['secret']}) as invoke:
            self.assertEqual(http.post('/api/papers/paper-test/prepare-practice',json={'request_id':'bad'}).status_code,400)
            invoke.assert_not_called()
            response=http.post('/api/papers/paper-test/prepare-practice',json={'request_id':str(uuid.uuid4())})
            self.assertEqual(response.status_code,201,response.text)
            self.assertIn('items',response.json());self.assertNotIn('session_id',response.text);self.assertNotIn('messages',response.text)
            self.assertEqual(http.post('/api/papers/missing/prepare-practice',json={'request_id':str(uuid.uuid4())}).status_code,404)

    def test_correction_merges_preserves_regions_and_survives_reanalysis(self):
        self.service.analyze(self.f.conn,'paper-test')
        values=list(self.f.conn.execute('SELECT * FROM questions ORDER BY number'))
        ids=[q['id'] for q in values]
        result=self.service.correct_questions('paper-test',dict(confirmed=True,questions=[dict(number='7',question_ids=ids)],delete_question_ids=[]))
        self.assertEqual(result['question_ids'],[ids[0]])
        self.assertIn(ids[1],result['deleted_question_ids'])
        with Database(self.config).session(write=True) as conn:
            self.service.analyze(conn,'paper-test')
            rows=list(conn.execute('SELECT * FROM questions'))
            self.assertEqual([r['number'] for r in rows],['7'])
            self.assertEqual(len(json.loads(rows[0]['regions_json'])),2)
        app,http=self.client()
        for i in (0,1):self.assertEqual(http.get('/api/questions/'+ids[0]+'/evidence',params={'region':i}).status_code,200)

    def test_correction_rejects_diagnosed_or_omitted_ids(self):
        self.f.apply()
        ids=[r[0] for r in self.f.conn.execute('SELECT id FROM questions')]
        with self.assertRaises(ValueError):self.service.correct_questions('paper-test',dict(confirmed=True,questions=[dict(number='1',question_ids=ids[:1])]))
        with self.assertRaisesRegex(Exception,'诊断'):self.service.correct_questions('paper-test',dict(confirmed=True,questions=[dict(number='1',question_ids=ids)]))

    def test_corrected_2023_and_2026_exam_fragments_are_rematched_atomically(self):
        for year,source in ((2023,'S01'),(2026,'S02')):
            with self.subTest(year=year):
                self.service.analyze(self.f.conn,'paper-test')
                ids=[r[0] for r in self.f.conn.execute('SELECT id FROM questions ORDER BY id')]
                self.f.conn.execute('UPDATE papers SET title=?,source_name=? WHERE id=?',
                    (f'{year}年数一',f'{year}年数一.pdf','paper-test'))
                self.f.conn.execute('UPDATE questions SET number=?,stem=? WHERE id=?',('2','A',ids[0]))
                self.f.conn.execute('UPDATE questions SET number=?,stem=? WHERE id=?',('1','Another question.',ids[1]))
                self.f.conn.execute('''INSERT INTO questions(id,paper_id,number,stem,correctness,created_at)
                    VALUES('fragment','paper-test','3','question.','unknown','now')''')
                for number,stem in ((1,'A question.'),(2,'Another question.')):
                    bid=f'{source}-{year}-{number}'
                    self.f.conn.execute('INSERT INTO bank_questions(id,source,stem,created_at) VALUES(?,?,?,?)',(bid,source,stem,'now'))
                    self.f.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,NULL,NULL)',(bid,json.dumps({'source_id':source}),'unused.png'))
                    self.f.conn.execute('INSERT INTO bank_identity VALUES(?,?,?,?,NULL)',(bid,1,str(year),number))
                self.f.conn.commit()
                body=dict(confirmed=True,questions=[dict(number='1',question_ids=[ids[0],'fragment']),dict(number='2',question_ids=[ids[1]])])
                # A failed matcher must roll back the correction and its history.
                with patch('app.services.papers.match_bank_questions',side_effect=RuntimeError('match failure')):
                    with self.assertRaisesRegex(RuntimeError,'match failure'):self.service.correct_questions('paper-test',body)
                with Database(self.config).session() as conn:
                    self.assertEqual(conn.execute('SELECT count(*) FROM questions').fetchone()[0],3)
                    self.assertEqual(conn.execute("SELECT count(*) FROM record_versions WHERE kind='question_segmentation'").fetchone()[0],0)
                self.service.correct_questions('paper-test',body)
                with Database(self.config).session(write=True) as conn:
                    result=list(conn.execute('SELECT number,match_bank_id,match_score FROM questions ORDER BY number'))
                    self.assertEqual([r['match_bank_id'] for r in result],[f'{source}-{year}-1',f'{source}-{year}-2'])
                    self.assertEqual([r['match_score'] for r in result],[.99,.99])
                    conn.execute('UPDATE questions SET match_bank_id=NULL,match_score=0')
                    with patch('app.services.papers.extract_pdf',side_effect=AssertionError('must preserve manual regions')):
                        repeated=self.service.analyze(conn,'paper-test')
                    self.assertEqual([q['match_bank_id'] for q in repeated['questions']],[f'{source}-{year}-1',f'{source}-{year}-2'])
                    # Correct number alone must not assert mathematical identity.
                    conn.execute("UPDATE questions SET stem='unrelated handwritten OCR' WHERE number='1'")
                    self.service.analyze(conn,'paper-test')
                    self.assertIsNone(conn.execute("SELECT match_bank_id FROM questions WHERE number='1'").fetchone()[0])
                    conn.execute('DELETE FROM questions');conn.execute('DELETE FROM record_versions')

    def test_correction_http_can_explicitly_remove_wrong_split(self):
        self.service.analyze(self.f.conn,'paper-test')
        ids=[r[0] for r in self.f.conn.execute('SELECT id FROM questions ORDER BY number')]
        app,http=self.client()
        response=http.post('/api/papers/paper-test/questions/correct',json=dict(confirmed=True,
            questions=[dict(number='3',question_ids=ids[:1])],delete_question_ids=ids[1:]))
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(http.get('/api/papers/paper-test/questions').json()['total'],1)
        self.assertEqual(response.json()['deleted_question_ids'],ids[1:])

    def test_uuid_validation_preserves_legacy_valid_spelling(self):
        from app.api.schemas import Attempt
        value=uuid.uuid4().hex
        self.assertEqual(Attempt(request_id=value).request_id,value)
        with self.assertRaises(ValueError):Attempt(request_id='not-uuid')

    def test_correction_missing_pdf_is_an_explicit_error(self):
        self.service.analyze(self.f.conn,'paper-test')
        ids=[r[0] for r in self.f.conn.execute('SELECT id FROM questions ORDER BY number')]
        self.f.pdf.unlink()
        with self.assertRaisesRegex(ValueError,'原PDF文件缺失'):
            self.service.correct_questions('paper-test',dict(confirmed=True,questions=[dict(number='1',question_ids=ids)]))

    def test_default_origin_denied_and_explicit_dev_origin_gets_cors(self):
        app,http=self.client()
        self.assertEqual(http.post('/api/preferences',json={},headers={'Origin':'http://localhost:5173'}).status_code,403)
        with patch.dict('os.environ',{'MATHLENS_DEV_ORIGINS':'http://localhost:5173'}):
            app,http=self.client()
            response=http.options('/api/preferences',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'POST'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.headers['access-control-allow-origin'],'http://localhost:5173')
            response=http.post('/api/preferences',json={},headers={'Origin':'http://localhost:5173'})
            self.assertEqual(response.status_code,200);self.assertEqual(response.headers['access-control-allow-origin'],'http://localhost:5173')
            self.assertEqual(http.post('/api/preferences',json={},headers={'Origin':'http://evil.invalid'}).status_code,403)
