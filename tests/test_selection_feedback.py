import copy,json,unittest,uuid
from app.learning.selection import normalize,public

class SelectionFeedbackTests(unittest.TestCase):
    def setUp(self):
        from test_execution_v2 import ExecutionTests
        self.f=ExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        _,self.scope=self.f.selection();self.inputs=json.loads(self.f.task['input_json'])

    def task(self,scope):return dict(self.f.task,input_json=json.dumps(dict(self.inputs,selection=scope)))

    def test_all_wrong_pairs_include_question_goal_and_legal_candidates(self):
        scope=copy.deepcopy(self.scope);template=scope['targets'][0]
        pairs=[('math1-2024-20','target-20-GS-06-042.rolle-theorem','legal-a'),('math1-2014-23','target-22-SUP-MLE-002','legal-b')]
        scope['targets']=[dict(copy.deepcopy(template),goal=dict(template['goal'],id=g),candidate_ids=[allowed]) for _,g,allowed in pairs]
        result=dict(selections=[dict(bank_id=b,goal_ids=[g]) for b,g,_ in pairs],limitations={g:'No suitable legal candidate' for _,g,_ in pairs})
        with self.assertRaises(ValueError) as error:normalize(self.f.conn,self.f.data,self.task(scope),result)
        for bid,gid,allowed in pairs:
            self.assertIn('bank_id='+bid,str(error.exception));self.assertIn('goal_id='+gid,str(error.exception));self.assertIn(allowed,str(error.exception))

    def test_limitations_and_both_quotas_are_reported_together(self):
        scope=copy.deepcopy(self.scope);t=scope['targets'][0];g=t['goal']['id'];tid=t['goal']['topic_ids'][0]
        scope['targets']=[dict(t,candidate_ids=['a','b','c','d']),dict(copy.deepcopy(t),goal=dict(t['goal'],id='empty'),candidate_ids=[])]
        source=next(iter(scope['candidates'].values()));scope['candidates']={b:dict(source,bank_id=b) for b in ('a','b','c','d')}
        value=dict(selections=[dict(bank_id=b,goal_ids=[g]) for b in ('a','b','c','d')],limitations={g:'','unknown':'extra'})
        with self.assertRaises(ValueError) as error:normalize(self.f.conn,self.f.data,self.task(scope),value)
        text=str(error.exception)
        for message in ('limitations缺少目标ID：empty','limitations含未知目标ID：unknown','goal_id='+g,'topic_id='+tid,'实际4'):self.assertIn(message,text)
        value['limitations']={g:'','empty':''}
        with self.assertRaisesRegex(ValueError,'goal_id=empty.*未选题目标'):normalize(self.f.conn,self.f.data,self.task(scope),value)

    def test_package_makes_reverse_pairing_explicit(self):
        view=public(self.scope)
        for candidate in view['candidates']:
            self.assertEqual(candidate['allowed_goal_ids'],[t['goal']['id'] for t in self.scope['targets'] if candidate['bank_id'] in t['candidate_ids']])

    def test_terminated_job_cancellation_has_same_summary_and_write_rules(self):
        from app.learning.workflows import enqueue,can_cancel,cancel_job
        from app.services.task_summary import TaskSummary
        from app.storage.database import Database
        from types import SimpleNamespace
        bridge=self.f.bridge();conn=self.f.conn
        with bridge.lock:
            job=enqueue(conn,self.f.root,self.f.data,'summarize_paper','paper-test',str(uuid.uuid4()))
            conn.execute("UPDATE workflow_jobs SET status='failed',task_id=? WHERE id=?",(self.f.task['id'],job['id']))
            conn.execute("UPDATE learning_tasks SET status='failed' WHERE id=?",(self.f.task['id'],));conn.commit()
            def current():return conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(job['id'],)).fetchone()
            for status in ('failed','interrupted','abandoned'):
                conn.execute('UPDATE learning_tasks SET status=? WHERE id=?',(status,self.f.task['id']));self.assertTrue(can_cancel(conn,current()))
            for status in ('queued','running','result_saved','completed'):
                conn.execute('UPDATE learning_tasks SET status=? WHERE id=?',(status,self.f.task['id']));self.assertFalse(can_cancel(conn,current()))
            conn.execute("UPDATE learning_tasks SET status='failed',result_id='saved' WHERE id=?",(self.f.task['id'],));self.assertFalse(can_cancel(conn,current()))
            conn.execute('UPDATE learning_tasks SET result_id=NULL WHERE id=?',(self.f.task['id'],));conn.commit()
            conn.execute("INSERT INTO learning_results VALUES('saved-proof',?,?,?,?,?,?)",(self.f.task['id'],'paper-test','prepare_practice','a'*64,'{}','now'))
            self.assertFalse(can_cancel(conn,current()))
            conn.execute("DELETE FROM learning_results WHERE id='saved-proof'")
            conn.execute("UPDATE workflow_jobs SET status='interrupted' WHERE id=?",(job['id'],));self.assertTrue(can_cancel(conn,current()))
            conn.execute("UPDATE workflow_jobs SET status='blocked' WHERE id=?",(job['id'],));self.assertFalse(can_cancel(conn,current()))
            conn.execute("UPDATE workflow_jobs SET status='failed' WHERE id=?",(job['id'],));conn.commit()
            summary=TaskSummary(SimpleNamespace(bridge=bridge,database=Database(__import__('database_fixture').config()))).read()
            self.assertIn('cancel',next(i for i in summary['items'] if i['id']==job['id'])['allowed_actions'])
            before=conn.execute('SELECT count(*) FROM papers').fetchone()[0]
            cancel_job(conn,job['id']);conn.commit()
            self.assertEqual(current()['status'],'abandoned');self.assertEqual(before,conn.execute('SELECT count(*) FROM papers').fetchone()[0])
            self.assertEqual(conn.execute('SELECT status FROM learning_tasks WHERE id=?',(self.f.task['id'],)).fetchone()[0],'failed')
