import json,unittest,uuid
from datetime import datetime,timezone,timedelta
from unittest.mock import patch
import test_f5_backend as fixtures
from app.learning.loop import submit_probe,assess_attempt
from app.services.profile import count


class ProfileOverviewTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.F5BackendTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.f.apply();self.conn=self.f.f.conn
        self.app,self.http=self.f.client()

    def grade(self,correct=True):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'synthetic work'})['attempt_id']
        assess_attempt(self.conn,aid,{'author':'fixture','correct':correct,'feedback':'结论已核对。'})
        self.conn.commit();return aid

    def test_compact_read_pagination_etag_and_write_invalidation(self):
        response=self.http.get('/api/profile/overview');self.assertEqual(response.status_code,200,response.text)
        value=response.json();self.assertNotIn('nodes',value);self.assertNotIn('weekly',value)
        self.assertIn('weak_spots',value);self.assertIsNone(value['conclusions']['independent_correct_comparison'])
        again=self.http.get('/api/profile/overview',headers={'If-None-Match':response.headers['etag']})
        self.assertEqual(again.status_code,304)
        trends=self.http.get('/api/profile/trends?weeks=8');self.assertEqual(trends.status_code,200,trends.text)
        self.assertEqual(len(trends.json()['weekly']),8);self.assertIn('from',trends.json()['period'])
        self.assertEqual(self.http.get('/api/profile/trends?weeks=53').status_code,400)
        self.assertEqual(self.http.get('/api/profile/nodes/missing/atoms').status_code,404)
        aid=self.grade()
        changed=self.http.get('/api/profile/overview',headers={'If-None-Match':response.headers['etag']})
        self.assertEqual(changed.status_code,200,changed.text)
        self.assertEqual(changed.json()['feedback']['unread_count'],1)

    def test_feedback_receipt_is_versioned_idempotent_and_does_not_change_result(self):
        aid=self.grade();old=self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0]
        value=self.http.get('/api/profile/overview').json();item=value['feedback']['recent_items'][0]
        body=dict(source='paper_practice',attempt_id=aid,feedback_revision=item['feedback_revision'],request_id=str(uuid.uuid4()))
        response=self.http.post('/api/feedback/read',json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.http.get('/api/profile/overview').json()['feedback']['unread_count'],0)
        self.assertTrue(self.http.post('/api/feedback/read',json=body).json()['reused'])
        self.assertEqual(self.http.post('/api/feedback/read',json=dict(body,attempt_id='other')).status_code,409)
        self.assertEqual(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0],old)
        updated=json.loads(old);updated['feedback']='新的有效批改。'
        self.conn.execute('UPDATE probe_attempts SET assessment_json=? WHERE id=?',(json.dumps(updated),aid));self.conn.commit()
        self.assertEqual(self.http.get('/api/profile/overview').json()['feedback']['unread_count'],1)
        self.assertEqual(self.http.post('/api/feedback/read',json=dict(body,request_id=str(uuid.uuid4()))).status_code,409)
        detail=self.http.get('/api/practices/paper-test-probe-test').json()['latest_attempt']
        self.assertTrue(detail['feedback_unread']);self.assertNotEqual(detail['feedback_revision'],item['feedback_revision'])

    def test_fact_counts_separate_assisted_unknown_and_pending(self):
        fs=[dict(correct=True,independent=i,pending=False) for i in (True,False,None)]
        fs.extend([dict(correct=False,independent=True,pending=False),dict(correct=None,independent=True,pending=True)])
        result=count(fs)
        self.assertEqual(result,dict(attempts=5,correct=3,independent_correct=1,assisted_correct=1,independence_unknown_correct=1,wrong=1,unjudged=1,pending_grading=1))

    def test_atom_states_are_lazy_and_no_records_do_not_become_weak(self):
        import test_knowledge_links as knowledge
        from app.main import create_app
        from fastapi.testclient import TestClient
        f=knowledge.KnowledgeLinksTests();f.setUp();self.addCleanup(f.doCleanups)
        with TestClient(create_app(f.config,agent_factory=None),base_url='http://127.0.0.1') as http:
            response=http.get('/api/profile/nodes/'+knowledge.TOPIC+'/atoms?limit=1')
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(response.json()['total'],1)
            self.assertEqual(response.json()['items'][0]['display_state'],'no_record')
            self.assertEqual(http.get('/api/profile/overview').json()['weak_spots'],[])


class ProfileEvidenceTests(unittest.TestCase):
    def test_weak_ranking_cites_saved_questions_and_first_error_without_atom_payload(self):
        import test_execution_v2 as execution
        from app.main import create_app
        from fastapi.testclient import TestClient
        import database_fixture as server
        f=execution.ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        f.conn.execute('UPDATE papers SET exam_date=?',(datetime.now().date().isoformat(),));f.conn.commit()
        f.case.m.save()  # Date is part of the saved source revision; refresh the real mapping.
        with TestClient(create_app(server.config(),agent_factory=None),base_url='http://127.0.0.1') as http:
            response=http.get('/api/profile/overview');self.assertEqual(response.status_code,200,response.text)
            overview=response.json();self.assertTrue(overview['weak_spots'])
            spot=overview['weak_spots'][0]
            self.assertGreaterEqual(spot['recent_failures'],1);self.assertIn('计算',spot['basis'])
            self.assertEqual(spot['evidence'][0]['first_error_stage'],'calculation')
            self.assertIn('漏乘内层导数',spot['evidence'][0]['first_error_evidence'])
            self.assertEqual(spot['kind'],'chapter')
            for subject in overview['subjects']:
                self.assertNotIn('atoms',subject)
                for chapter in subject['chapters']:self.assertNotIn('atoms',chapter)
