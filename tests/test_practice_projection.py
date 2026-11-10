import json,unittest
from fastapi.testclient import TestClient
import test_execution_v2 as execution
import test_free_practice as free
import database_fixture as server
from app.main import create_app
from app.learning.loop import submit_probe,assess_attempt
from app.bank.access import reveal,save_preferences


class PracticeProjectionTests(unittest.TestCase):
    def test_list_correctness_fixed_source_and_reference_placeholder(self):
        f=execution.ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        meta=dict(book=dict(part='强化篇',chapter='第3章',number='5',locator='chapter-34#q5'))
        f.conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(json.dumps(meta),execution.prepared.BANK));f.conn.commit()
        f.save_selection()
        row=f.conn.execute('SELECT * FROM diagnostic_probes WHERE bank_id=?',(execution.prepared.BANK,)).fetchone();pid=row['id']
        reveal(f.conn,execution.prepared.BANK,'question',True)
        aid=submit_probe(f.conn,pid,{'response':'synthetic answer'})['attempt_id']
        assess_attempt(f.conn,aid,{'author':'fixture','correct':False,'answer_status':'partial','feedback':'部分成立。','reference_reasoning':'参考解析见原图'})
        reveal(f.conn,execution.prepared.BANK,'analysis',True)
        # Later navigation changes do not change the source on the saved exercise.
        meta['book']['number']='99';f.conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(json.dumps(meta),execution.prepared.BANK));f.conn.commit()
        with TestClient(create_app(server.config(),agent_factory=None),base_url='http://127.0.0.1') as http:
            response=http.get('/api/practices');self.assertEqual(response.status_code,200,response.text)
            card=next(c for g in response.json()['items'] for c in g['items'] if c['id']==pid)
            self.assertEqual(card['origin'],'paper');self.assertEqual(card['latest_correctness'],'partial')
            self.assertIsNone(card['batch_id']);self.assertEqual(card['access']['collection_label'],'其他')
            self.assertEqual(card['access']['book']['number'],'5')
            detail=http.get('/api/practices/'+pid).json()
            self.assertIsNone(detail['latest_attempt']['assessment']['reference_reasoning'])
            self.assertEqual(json.loads(f.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(aid,)).fetchone()[0])['reference_reasoning'],'参考解析见原图')

    def test_free_403_reason_reserved_wins_and_no_accidental_reveal(self):
        f=free.FreePracticeTests();f.setUp();self.addCleanup(f.doCleanups)
        f.conn.execute("UPDATE bank_identity SET math_type=1,year='2026',number=10 WHERE bank_id='bank-test'")
        f.conn.execute('DELETE FROM bank_views');f.conn.commit()
        for url,body in [(f.url,None),(f.url+'/attempts',dict(request_id='00000000-0000-0000-0000-000000000001',choice='B'))]:
            r=f.http.get(url) if body is None else f.http.post(url,json=body)
            self.assertEqual(r.status_code,403,r.text);self.assertEqual(r.json()['reason'],'masked');self.assertEqual(r.json()['message'],r.json()['error'])
        save_preferences(f.conn,{'reserved':[{'math_type':1,'year':'2026'}]});f.conn.commit()
        r=f.http.get(f.url);self.assertEqual(r.status_code,403);self.assertEqual(r.json()['reason'],'reserved')
        self.assertEqual(f.conn.execute('SELECT count(*) FROM bank_views').fetchone()[0],0)
