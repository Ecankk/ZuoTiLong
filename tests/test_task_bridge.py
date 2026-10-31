import json
import time
import unittest
import uuid
from unittest.mock import patch

from app.agent.bridge import CodexBridge
from app.learning.tasks import task_record
from test_codex_bridge import FakeCodex
import test_learning_tasks as task_fixtures
import database_fixture as server


class TaskBridgeTests(unittest.TestCase):
    def setUp(self):
        self.fixture=task_fixtures.LearningTaskTests();self.fixture.setUp()
        self.bridge=CodexBridge(self.fixture.root,self.fixture.data,FakeCodex)
        self.bridge.learning_db=server.DB_PATH
        self.patcher=patch('app.agent.tools.connection',lambda data:server.connect());self.patcher.start()
        self.bridge.connect();self.wait(lambda:self.bridge.connected)

    def tearDown(self):
        self.bridge.close();self.patcher.stop();self.fixture.tearDown()

    def wait(self,predicate):
        deadline=time.monotonic()+4
        while not predicate():
            if time.monotonic()>deadline:self.fail('task transition timed out')
            time.sleep(.01)

    def start(self):
        self.bridge.submit_task('analyze_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:bool(self.bridge._active()['codex_turn_id']))
        return self.bridge._active()

    def call(self,action,payload):
        turn=self.bridge._active()
        self.bridge.event({'method':'item/tool/call','id':uuid.uuid4().hex,'params':{
            'threadId':self.bridge.state['session_id'],'turnId':turn['codex_turn_id'],
            'tool':'mathlens','arguments':{'action':action,'payload':payload}}})
        result=self.bridge.transport.sent[-1]['result']
        return result, json.loads(result['contentItems'][0]['text']) if result['success'] else result['contentItems'][0]['text']

    def end(self,status='completed'):
        turn=self.bridge._active()
        self.bridge.event({'method':'turn/completed','params':{'threadId':self.bridge.state['session_id'],
                          'turn':{'id':turn['codex_turn_id'],'status':status,'items':[]}}})

    def save_analysis(self):
        turn=self.start()
        task=task_record(self.fixture.conn,turn['task_id'])
        self.fixture.kind='analyze_paper';self.fixture.task=task
        self.call('read_paper',{'paper_id':'paper-test','pages':[1]})
        result,payload=self.call('apply_report',{'result':self.fixture.analysis()})
        self.assertTrue(result['success'],payload)
        return turn,task,payload

    def start_practice(self):
        self.bridge.submit_task('prepare_practice','paper-test',str(uuid.uuid4()))
        self.wait(lambda:self.bridge._active() and bool(self.bridge._active().get('codex_turn_id')))

    def test_saved_analysis_waits_for_explicit_practice_on_same_session(self):
        turn,task,saved=self.save_analysis()
        self.end()
        self.assertTrue(self.bridge.snapshot()['can_submit'])
        self.assertFalse(self.bridge._active())
        self.assertEqual(self.fixture.conn.execute("SELECT COUNT(*) FROM learning_tasks WHERE kind='prepare_practice'").fetchone()[0],0)
        self.start_practice()
        self.assertEqual(self.bridge.state['session_id'],'fixed-test-session')
        self.assertEqual(sum(method=='thread/start' for method,_ in self.bridge.transport.calls),1)
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)
        active=self.bridge._active();self.fixture.kind='prepare_practice'
        self.fixture.task=task_record(self.fixture.conn,active['task_id'])
        result,payload=self.call('apply_report',{'result':self.fixture.envelope({'goals':[],'exercises':[],
                                            'limitations':['no suitable candidate']})})
        self.assertTrue(result['success'],payload)
        self.end()
        self.assertTrue(self.bridge.snapshot()['can_submit'])
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0],2)
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)

    def test_final_text_alone_repairs_twice_then_stays_locked(self):
        self.start()
        for count in (1,2):
            old=self.bridge._active()['codex_turn_id']
            self.end()
            self.wait(lambda:bool(self.bridge._active()['codex_turn_id']) and self.bridge._active()['codex_turn_id']!=old)
            self.assertEqual(self.bridge._active()['repair_attempts'],count)
        self.end()
        self.assertEqual(self.bridge.state['status'],'failed')
        self.assertTrue(self.bridge.snapshot()['input_locked'])
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0],0)

    def test_failed_practice_retry_keeps_analysis_and_only_retries_practice(self):
        self.save_analysis();self.end()
        self.start_practice()
        task_id=self.bridge._active()['task_id'];old=self.bridge._active()['codex_turn_id']
        self.end('failed')
        self.bridge.transport.history=[{'id':old,'status':'failed'}]
        self.bridge.retry()
        self.wait(lambda:bool(self.bridge._active()['codex_turn_id']) and self.bridge._active()['codex_turn_id']!=old)
        self.assertEqual(self.bridge._active()['task_id'],task_id)
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)
        self.assertEqual(self.fixture.conn.execute("SELECT COUNT(*) FROM learning_tasks WHERE kind='analyze_paper'").fetchone()[0],1)

    def test_old_tool_call_cannot_write_after_explicit_practice_start(self):
        old,task,_=self.save_analysis();old_id=old['codex_turn_id'];payload=self.fixture.analysis()
        self.end();self.start_practice()
        before=self.fixture.conn.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0]
        self.bridge.event({'method':'item/tool/call','id':'old-call','params':{'threadId':self.bridge.state['session_id'],
                          'turnId':old_id,'tool':'mathlens','arguments':{'action':'apply_report','payload':{'result':payload}}}})
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0],before)
        self.assertTrue(self.bridge.snapshot()['input_locked'])

    def test_reconnect_after_saved_analysis_waits_without_starting_practice(self):
        turn,task,_=self.save_analysis();tid=turn['codex_turn_id']
        self.bridge.close()
        def factory(root,data,notify,disconnected):
            transport=FakeCodex(root,data,notify,disconnected)
            transport.history=[{'id':tid,'status':'completed'}]
            return transport
        self.bridge=CodexBridge(self.fixture.root,self.fixture.data,factory)
        self.bridge.learning_db=server.DB_PATH
        self.bridge.connect()
        self.wait(lambda:self.bridge.connected and self.bridge.snapshot()['can_submit'])
        self.assertEqual(self.bridge.state['session_id'],'fixed-test-session')
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)
        self.assertFalse(any(m=='thread/start' for m,_ in self.bridge.transport.calls))
        self.assertEqual(self.fixture.conn.execute("SELECT COUNT(*) FROM learning_tasks WHERE kind='prepare_practice'").fetchone()[0],0)

    def test_persisted_legacy_auto_chain_does_not_start_on_reconnect(self):
        self.bridge.state['pending_chain']={'paper_id':'paper-test','request_id':str(uuid.uuid4()),'workflow_id':'old-chain'}
        self.bridge._continue_chain()
        self.assertNotIn('pending_chain',self.bridge.state)
        self.assertFalse(self.bridge._active())
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM learning_tasks').fetchone()[0],0)

    def test_control_loss_invalidates_old_task_write_ticket(self):
        from app.learning.tasks import check_lease
        turn=self.start();old=self.bridge._task_lease(turn).copy()
        generation=self.bridge.generation
        self.bridge.event({'method':'thread/closed','params':{'threadId':self.bridge.state['session_id']}},generation)
        with self.assertRaisesRegex(ValueError,'旧连接'):
            check_lease(self.fixture.conn,old)
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0],0)
        self.assertTrue(self.bridge.snapshot()['input_locked'])

    def test_summary_task_routes_to_update_skill_with_saved_reference_ids(self):
        self.fixture.fixture.apply()
        self.bridge.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:bool(self.bridge._active()['codex_turn_id']))
        text=self.bridge._active()['text']
        self.assertIn('mathlens-learning-update',text)
        self.assertIn('不重新求解原卷',text)
        self.assertNotIn('先核验解法并核对整卷可见作答',self.bridge._active()['inputs'][0]['text'])
        ok,context=self.call('context',{'paper_id':'paper-test'})
        self.assertTrue(ok['success'],context)
        self.assertEqual(context['task_packages'],[])
        refs=context['learning_task']['allowed_source_refs']
        self.assertTrue(refs)
        self.assertEqual({r['kind'] for r in refs},{'question','report'})
        for ref in refs:
            table='questions' if ref['kind']=='question' else 'agent_reports'
            row=self.fixture.conn.execute('SELECT paper_id FROM '+table+' WHERE id=?',(ref['id'],)).fetchone()
            self.assertEqual(row[0],'paper-test')

    def test_unverified_analysis_is_saved_without_selecting_practice(self):
        turn=self.start();self.fixture.kind='analyze_paper'
        self.fixture.task=task_record(self.fixture.conn,turn['task_id'])
        self.call('read_paper',{'paper_id':'paper-test','pages':[1]})
        payload=self.fixture.analysis()
        payload['result']['report']['review']={'status':'needs_review','issues':['original choice is unclear']}
        result,receipt=self.call('apply_report',{'result':payload})
        self.assertTrue(result['success'],receipt)
        self.end()
        self.assertTrue(self.bridge.snapshot()['can_submit'])
        self.assertIn('暂未开始选题',self.bridge.state['activity'])
        self.assertEqual(self.fixture.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)
        self.assertEqual(self.fixture.conn.execute("SELECT COUNT(*) FROM learning_tasks WHERE kind='prepare_practice'").fetchone()[0],0)

    def test_crop_read_preserves_color_and_does_not_claim_a_full_page_read(self):
        turn=self.start()
        result,content=self.call('read_paper',{'paper_id':'paper-test','regions':[{'page':1,'bbox':[20,30,300,200]}]})
        self.assertTrue(result['success'],content)
        self.assertEqual(content['read_scope'],'regions')
        self.assertEqual(content['page_dimensions'][0]['image_scale'],3)
        reads=self.fixture.conn.execute('SELECT kind FROM task_reads WHERE task_id=?',(turn['task_id'],)).fetchall()
        self.assertEqual([r[0] for r in reads],['paper_region'])
        bad,_=self.call('read_paper',{'paper_id':'paper-test','regions':[{'page':1,'bbox':[0,0,9999,9999]}]})
        self.assertFalse(bad['success'])


if __name__=='__main__':unittest.main()
