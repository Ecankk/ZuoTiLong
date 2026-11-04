import json,time,unittest,uuid
from unittest.mock import patch
from app.agent.bridge import CodexBridge
from app.learning.tasks import task_record
from test_codex_bridge import FakeCodex
import test_learning_tasks as task_fixtures
import database_fixture as server

class TaskBridgeTests(unittest.TestCase):
    def tearDown(self):pass
    def setUp(self):
        self.fixture=task_fixtures.LearningTaskTests();self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.bridge=CodexBridge(self.fixture.root,self.fixture.data,FakeCodex)
        self.addCleanup(self.bridge.close)
        self.bridge.learning_db=server.DB_PATH
        self.patcher=patch('app.agent.tools.connection',lambda data:server.connect());self.patcher.start();self.addCleanup(self.patcher.stop)
        self.bridge.connect();self.wait(lambda:self.bridge.connected)
    def wait(self,predicate):
        deadline=time.monotonic()+5
        while not predicate():
            if time.monotonic()>deadline:self.fail('task transition timed out')
            time.sleep(.01)
    def start(self):
        self.bridge.submit_task('analyze_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:self.bridge._active() and not self.bridge._active()['codex_turn_id'].startswith('pending-'))
        return self.bridge._active()
    def call(self,action,payload):
        turn=self.bridge._active();transport=self.bridge.transport
        self.bridge.event({'method':'item/tool/call','id':uuid.uuid4().hex,'params':{
            'threadId':turn['session_id'],'turnId':turn['codex_turn_id'],'tool':'mathlens',
            'arguments':{'action':action,'payload':payload}}})
        result=transport.sent[-1]['result']
        return result,json.loads(result['contentItems'][0]['text']) if result['success'] else result['contentItems'][0]['text']
    def end(self,status='completed'):
        turn=self.bridge._active()
        if turn:self.bridge.event({'method':'turn/completed','params':{'threadId':turn['session_id'],
            'turn':{'id':turn['codex_turn_id'],'status':status,'items':[]}}})
    def save_analysis(self):
        turn=self.start();task=task_record(self.fixture.conn,turn['task_id']);self.fixture.kind='analyze_paper';self.fixture.task=task
        self.call('read_paper',{'paper_id':'paper-test','pages':[1]})
        result,payload=self.call('apply_report',{'result':self.fixture.analysis()})
        self.assertTrue(result['success'],payload);return turn,task,payload
    def test_successful_delivery_completes_without_remote_final_text(self):
        turn,task,saved=self.save_analysis();self.wait(lambda:not self.bridge.finishing)
        self.assertIsNone(self.bridge._active());self.assertEqual(turn['status'],'completed')
        self.assertEqual(task_record(self.fixture.conn,task['id'])['status'],'completed')
    def test_final_text_without_delivery_fails_instead_of_auto_repairing(self):
        turn=self.start();self.end();self.wait(lambda:not self.bridge.finishing)
        self.assertEqual(turn['status'],'failed');self.assertIsNone(self.bridge._active())
        self.assertEqual(len(self.bridge.state['turns']),1)
    def test_foreign_and_old_generation_events_cannot_complete_active_task(self):
        turn=self.start()
        self.bridge.event({'method':'turn/completed','params':{'threadId':'foreign','turn':{'id':turn['codex_turn_id']}}})
        self.bridge.event({'method':'turn/completed','params':{'threadId':turn['session_id'],'turn':{'id':turn['codex_turn_id']}}},self.bridge.generation-1)
        self.assertIs(self.bridge._active(),turn)
    def test_memory_tools_removed_from_learning_schema(self):
        from app.agent.tools import ACTIONS
        self.assertNotIn('memory_read',ACTIONS);self.assertNotIn('memory_write',ACTIONS)
