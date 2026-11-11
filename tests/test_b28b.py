import json,unittest,uuid
from datetime import datetime
from unittest.mock import patch
import test_b28 as fixtures


class PaperPatchTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.PaperMetadataTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.http=self.f.http;self.conn=self.f.conn

    def pending(self):
        self.f.upload(self.f.pdf('first'))
        value=self.f.upload(self.f.pdf('second')).json()
        pid=value['paper']['id']
        detail=self.http.get('/api/papers/'+pid).json()
        self.assertEqual(detail['decision_revision'],value['decision_revision'])
        return pid,dict(confirmed=True,request_id=str(uuid.uuid4()),decision='retake',decision_revision=detail['decision_revision'])

    def reason(self,response,expected):
        self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(response.json()['reason'],expected)
        self.assertEqual(response.json()['message'],response.json()['error'])

    def test_detail_revision_works_and_conflicts_are_structured(self):
        pid,body=self.pending();url='/api/papers/'+pid+'/import-decision'
        self.reason(self.http.post(url,json=dict(body,decision_revision='stale')),'revision_stale')
        with patch('app.services.paper_metadata.busy',return_value=True):
            self.reason(self.http.post(url,json=body),'task_active')
        response=self.http.post(url,json=body);self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(self.http.post(url,json=body).json()['reused'])
        self.reason(self.http.post(url,json=dict(body,decision='withdraw')),'request_conflict')
        # A diagnosed paper cannot use this upload-only decision to erase history.
        self.f.f.f.apply();self.conn.execute("UPDATE papers SET import_decision='pending_duplicate' WHERE id='paper-test'");self.conn.commit()
        revision=self.http.get('/api/papers/paper-test').json()['decision_revision']
        self.reason(self.http.post('/api/papers/paper-test/import-decision',json=dict(body,request_id=str(uuid.uuid4()),decision='withdraw',decision_revision=revision)),'has_history')

    def test_dates_active_withdrawn_and_request_conflict(self):
        pid,decision=self.pending()
        body=dict(confirmed=True,request_id=str(uuid.uuid4()),paper_ids=[pid],exam_date='2026-01')
        with patch('app.services.paper_metadata.busy',return_value=True):
            self.reason(self.http.post('/api/papers/dates',json=body),'task_active')
        self.assertEqual(self.http.post('/api/papers/dates',json=body).status_code,200)
        self.reason(self.http.post('/api/papers/dates',json=dict(body,exam_date='2026-02')),'request_conflict')
        response=self.http.post('/api/papers/'+pid+'/import-decision',json=dict(decision,decision='withdraw'))
        self.assertEqual(response.status_code,200,response.text)
        self.reason(self.http.post('/api/papers/dates',json=dict(body,request_id=str(uuid.uuid4()))),'withdrawn')

    def test_sha_reuse_reports_date_ignored_without_changing_dates(self):
        content=self.f.pdf('same');first=self.f.upload(content,exam_date='2026-01').json()
        pid=first['paper']['id'];self.assertFalse(first['date_ignored'])
        for fields,ignored in [({},False),({'exam_date':'2026-01'},False),({'exam_date':'2026-02'},True),({'exam_date_precision':'unknown'},True)]:
            response=self.f.upload(content,**fields);self.assertEqual(response.status_code,200,response.text)
            value=response.json();self.assertEqual(value['date_ignored'],ignored)
            self.assertEqual(value['paper']['id'],pid);self.assertEqual(value['paper']['exam_date'],'2026-01')
        self.assertEqual(self.conn.execute('SELECT exam_date FROM papers WHERE id=?',(pid,)).fetchone()[0],'2026-01')

    def test_practice_evidence_keeps_iso_attempt_time_and_b29_label(self):
        import test_free_practice as free
        f=free.FreePracticeTests();f.setUp();self.addCleanup(f.doCleanups)
        f.submit(choice='A')
        mistake=f.http.get('/api/profile/overview').json()['recent_mistakes'][0]
        self.assertIn('T',mistake['occurred_at']);datetime.fromisoformat(mistake['occurred_at'])
        self.assertNotEqual(mistake['label'],'自由练习')
