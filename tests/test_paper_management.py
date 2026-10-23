import copy
from unittest.mock import Mock, patch
from urllib.parse import urlparse
import unittest

import test_learning_loop as fixtures
import server
from learning_loop import apply_report, assess_attempt, skill_profile, submit_probe
from agent_workspace import workspace_context


class PaperManagementTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LearningLoopTests()
        self.fixture.setUp()
        self.conn=self.fixture.conn
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
        handler=server.Handler.__new__(server.Handler)
        handler.read_json=lambda:{'confirmed':False}
        handler.send_json=Mock()
        with patch.object(server,'analyze_paper_record') as analyze,patch.object(server,'BRIDGE',None):
            handler.api_post(urlparse('/api/papers/paper-test/resummarize'))
            self.assertEqual(handler.send_json.call_args.args[1],400)
            handler.read_json=lambda:{'confirmed':True}
            handler.api_post(urlparse('/api/papers/paper-test/resummarize'))
            self.assertEqual(handler.send_json.call_args.args[1],400)
            analyze.assert_not_called()
        bridge=Mock(connected=True)
        with patch.object(server,'analyze_paper_record',return_value={'paper':{'id':'paper-test'}}),patch.object(server,'BRIDGE',bridge):
            handler.api_post(urlparse('/api/papers/paper-test/resummarize'))
        self.assertTrue(handler.send_json.call_args.args[0]['agent_submitted'])
        self.assertEqual(bridge.submit.call_args.args[2],{'paper_id':'paper-test'})

    def test_http_archived_lists_and_restore_are_explicit(self):
        self.conn.commit()
        handler=server.Handler.__new__(server.Handler)
        response={}
        handler.send_json=lambda body,status=200:response.update(body=body,status=status)
        handler.read_json=lambda:{'confirmed':False}
        handler.api_post(urlparse('/api/papers/paper-test/archive'))
        self.assertEqual(response['status'],400)
        handler.read_json=lambda:{'confirmed':True}
        handler.api_post(urlparse('/api/papers/paper-test/archive'))
        handler.api_get(urlparse('/api/papers'))
        self.assertEqual(response['body']['papers'],[])
        handler.api_get(urlparse('/api/papers?archived=1'))
        self.assertEqual(response['body']['papers'][0]['id'],'paper-test')
        handler.api_post(urlparse('/api/papers/paper-test/restore'))
        handler.api_get(urlparse('/api/papers'))
        self.assertEqual(response['body']['papers'][0]['id'],'paper-test')


if __name__=='__main__':unittest.main()
