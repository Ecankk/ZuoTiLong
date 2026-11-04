import copy
from unittest.mock import Mock, patch
from urllib.parse import urlparse
import unittest

import test_learning_loop as fixtures
import database_fixture as server
from app.learning.loop import apply_report, assess_attempt, skill_profile, submit_probe
from app.agent.workspace import workspace_context


class PaperManagementTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LearningLoopTests()
        self.fixture.setUp()
        self.conn=self.fixture.conn
        self.fixture.report.update(completion='complete',review={'status':'verified','issues':[]})
        self.fixture.apply()

    def tearDown(self):
        self.fixture.tearDown()

    def test_legacy_database_migration_keeps_paper_and_evidence(self):
        for field in ('updated_at','archived_at','score_confirmed_at','math_type'):
            self.conn.execute('ALTER TABLE papers DROP COLUMN '+field)
        self.conn.commit()
        server.init_db()
        paper=self.conn.execute('SELECT * FROM papers WHERE id=?',('paper-test',)).fetchone()
        self.assertEqual(paper['updated_at'],paper['created_at'])
        self.assertIsNone(paper['archived_at'])
        self.assertIsNone(paper['score_confirmed_at'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],1)

    def test_archive_restore_preserves_evidence_and_recalculates_profile(self):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'my reasoning'})['attempt_id']
        assess_attempt(self.conn,aid,{'correct':False,'feedback':'visible error','author':'test'})
        before={name:self.conn.execute('SELECT count(*) FROM '+name).fetchone()[0] for name in ('questions','agent_reports','probe_attempts','learning_events','bank_questions')}
        with self.assertRaises(ValueError):server.set_paper_archive(self.conn,'paper-test',True,False)
        server.set_paper_archive(self.conn,'paper-test',True,True)
        self.assertEqual(skill_profile(self.conn),[])
        self.assertEqual(workspace_context(self.conn,self.fixture.root)['papers'],[])
        self.assertTrue(server.set_paper_archive(self.conn,'paper-test',True,True)['reused'])
        server.set_paper_archive(self.conn,'paper-test',False,True)
        self.assertEqual(skill_profile(self.conn)[0]['failures'],3)
        self.assertEqual(skill_profile(self.conn)[0]['probe_ids'],['paper-test-probe-test'])
        for name,count in before.items():self.assertEqual(self.conn.execute('SELECT count(*) FROM '+name).fetchone()[0],count)

    def test_archived_paper_rejects_report_submission_and_assessment(self):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'my reasoning'})['attempt_id']
        server.set_paper_archive(self.conn,'paper-test',True,True)
        with self.assertRaises(ValueError):submit_probe(self.conn,'paper-test-probe-test',{'response':'new'})
        with self.assertRaises(ValueError):assess_attempt(self.conn,aid,{'correct':True,'feedback':'new','author':'test'})
        with self.assertRaises(ValueError):apply_report(self.conn,'paper-test',self.fixture.report,fixtures.ROOT)
        self.assertIsNone(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0])

    def test_score_confirmation_rejects_invalid_numbers_and_keeps_audit(self):
        for value in (-1,151,float('nan'),float('inf'),True,'100'):
            with self.assertRaises(ValueError):server.confirm_paper_score(self.conn,'paper-test',{'score':value,'math_type':1,'confirmed':True})
        with self.assertRaises(ValueError):server.confirm_paper_score(self.conn,'paper-test',{'score':0,'math_type':1})
        server.confirm_paper_score(self.conn,'paper-test',{'score':0,'math_type':1,'confirmed':True})
        server.confirm_paper_score(self.conn,'paper-test',{'score':103.5,'math_type':1,'confirmed':True})
        row=self.conn.execute('SELECT * FROM papers WHERE id=?',('paper-test',)).fetchone()
        self.assertEqual(row['score'],103.5)
        self.assertTrue(row['score_confirmed_at'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_versions WHERE kind='paper_score'").fetchone()[0],2)

    def test_new_summary_keeps_old_report_attempt_and_confirmed_score(self):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'my reasoning'})['attempt_id']
        server.confirm_paper_score(self.conn,'paper-test',{'score':100,'math_type':1,'confirmed':True})
        revised=copy.deepcopy(self.fixture.report)
        revised['summary']='reviewed again with new evidence'
        result=apply_report(self.conn,'paper-test',revised,fixtures.ROOT)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT report_id FROM question_diagnoses LIMIT 1').fetchone()[0],result['report_id'])
        self.assertEqual(self.conn.execute('SELECT response FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0],'my reasoning')
        self.assertEqual(self.conn.execute('SELECT score FROM papers LIMIT 1').fetchone()[0],100)

    def test_resummarize_needs_confirmation_and_connected_agent_before_extraction(self):
        from http_support import client
        from app.services.papers import PaperService
        self.conn.commit()
        with patch.object(PaperService,'analyze') as analyze,client() as http:
            self.assertEqual(http.post('/api/papers/paper-test/resummarize',json={'confirmed':False}).status_code,400)
            self.assertEqual(http.post('/api/papers/paper-test/resummarize',json={'confirmed':True}).status_code,400)
            analyze.assert_not_called()
        bridge=Mock(connected=True)
        import threading
        bridge.lock=threading.RLock()
        bridge.state={}
        bridge.connecting=False
        bridge.auto_connect=False
        bridge.availability.return_value={'status':'available','reason':None,'message':'available'}
        bridge.assert_user_write_allowed=Mock()
        with patch.object(PaperService,'analyze') as analyze,client(bridge) as http:
            response=http.post('/api/papers/paper-test/resummarize',json={'confirmed':True})
            self.assertEqual(response.status_code,201,response.text)
            self.assertTrue(response.json()['agent_submitted'])
            analyze.assert_not_called()
        self.assertEqual(bridge.queue_task.call_args.args[:2],('summarize_paper','paper-test'))


    def test_http_archived_lists_and_restore_are_explicit(self):
        from http_support import client
        self.conn.commit()
        with client() as http:
            self.assertEqual(http.post('/api/papers/paper-test/archive',json={'confirmed':False}).status_code,400)
            self.assertEqual(http.post('/api/papers/paper-test/archive',json={'confirmed':True}).status_code,200)
            self.assertEqual(http.get('/api/papers').json()['papers'],[])
            self.assertEqual(http.get('/api/papers?archived=1').json()['papers'][0]['id'],'paper-test')
            self.assertEqual(http.post('/api/papers/paper-test/restore',json={'confirmed':True}).status_code,200)
            self.assertEqual(http.get('/api/papers').json()['papers'][0]['id'],'paper-test')



if __name__=='__main__':unittest.main()
