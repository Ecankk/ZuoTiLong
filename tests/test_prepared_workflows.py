"""Default web requests map original evidence before selecting prepared items."""
import json,unittest,uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
import database_fixture as server
import test_prepared_practice as prepared
import test_task_bridge as bridge_fixtures
from app.config import AppConfig
from app.main import create_app
from app.agent.bridge import CodexBridge
from app.learning.tasks import task_record
from app.learning.workflows import request_practice,listing


class PreparedWorkflowTests(unittest.TestCase):
    wait=bridge_fixtures.TaskBridgeTests.wait
    call=bridge_fixtures.TaskBridgeTests.call
    end=bridge_fixtures.TaskBridgeTests.end

    def setUp(self):
        self.case=prepared.PreparedPracticeTests();self.case.setUp();self.addCleanup(self.case.tearDown)
        self.fixture=self.case.f;self.conn=self.case.conn
        self.bridge=CodexBridge(self.fixture.root,self.fixture.data,bridge_fixtures.FakeCodex)
        self.bridge.learning_db=server.DB_PATH
        self.addCleanup(lambda:self.bridge.close())
        self.patcher=patch('app.agent.tools.connection',lambda data:server.connect());self.patcher.start();self.addCleanup(self.patcher.stop)
        self.bridge.auto_connect=True;self.bridge.connect();self.wait(lambda:self.bridge.connected)

    def active(self,kind):
        self.wait(lambda:self.bridge._active() and self.bridge._active().get('task_kind')==kind
                  and self.bridge._active().get('codex_turn_id') and not self.bridge._active()['codex_turn_id'].startswith('pending-'))
        task=task_record(self.conn,self.bridge._active()['task_id'])
        self.fixture.task=task;self.fixture.kind=kind
        return json.loads(task['input_json'])

    def save_mapping(self):
        inputs=self.active('organize_knowledge');mappings=[]
        for source in inputs['knowledge_sources']:
            ok,data=self.call('task_context',{'source_ids':[source['source_id']]});self.assertTrue(ok['success'],data)
            mappings.append({'source_id':source['source_id'],'source_revision':source['source_revision'],
                'topic_ids':[prepared.TOPIC],'reason':'Associate the saved isolated evidence.',
                'event_topics':[{'event_id':e['id'],'topic_ids':[prepared.TOPIC]} for e in source['events']]})
        ok,data=self.call('task_context',{'topic_ids':[prepared.TOPIC]});self.assertTrue(ok['success'],data)
        ok,data=self.call('apply_report',{'result':self.fixture.envelope({'summary':'Indexed saved evidence only.',
            'new_nodes':[],'mappings':mappings,'limitations':[]})})
        self.assertTrue(ok['success'],data)
        return data

    def request(self):
        self.bridge.queue_task('prepare_practice','paper-test',str(uuid.uuid4()),index_after=True,practice_contract_version='1.9')

    def save_plan(self):
        inputs=self.active('prepare_practice');self.assertEqual(inputs['contract_version'],'1.10')
        for action,payload in (('task_context',{'topic_ids':[prepared.TOPIC]}),
                ('catalog',{'topic_ids':[prepared.TOPIC]}),('read_bank',{'bank_id':prepared.BANK,'role':'all'})):
            ok,data=self.call(action,payload);self.assertTrue(ok['success'],data)
        ok,data=self.call('apply_report',{'result':self.case.payload()});self.assertTrue(ok['success'],data)

    def test_direct_practice_request_automatically_maps_missing_originals(self):
        self.request();inputs=self.active('organize_knowledge')
        self.assertEqual(inputs['contract_version'],'1.8')
        self.assertTrue(inputs['knowledge_sources'])
        self.assertTrue(all(s['kind']=='question' for s in inputs['knowledge_sources']))
        self.save_mapping();self.end();self.active('prepare_practice')

    def test_valid_original_mappings_skip_the_extra_agent_turn(self):
        self.case.m.save();self.request();self.active('prepare_practice')
        self.assertEqual([t['task_kind'] for t in self.bridge.state['turns']],['prepare_practice'])

    def test_duplicate_request_after_mapping_still_refers_to_the_original_intent(self):
        request=str(uuid.uuid4())
        original=request_practice(self.conn,self.fixture.root,self.fixture.data,'paper-test',request)
        self.conn.commit();self.bridge.workflow_wakeup.set()
        self.save_mapping();self.end();self.active('prepare_practice')
        count=len(listing(self.conn))
        repeat=request_practice(self.conn,self.fixture.root,self.fixture.data,'paper-test',request)
        self.assertEqual(repeat['id'],original['id']);self.assertEqual(len(listing(self.conn)),count)

    def test_new_policy_does_not_reinterpret_an_existing_old_analysis_job(self):
        from app.learning.workflows import enqueue
        request=str(uuid.uuid4())
        job=enqueue(self.conn,self.fixture.root,self.fixture.data,'analyze_paper','paper-test',request,auto_prepare=True)
        self.assertEqual(job['practice_contract_version'],'1.6')
        with self.assertRaisesRegex(ValueError,'后续选题策略'):
            enqueue(self.conn,self.fixture.root,self.fixture.data,'analyze_paper','paper-test',request,
                    auto_prepare=True,practice_contract_version='1.9')

    def test_web_practice_request_cannot_hide_an_unrelated_attempt_argument(self):
        config=AppConfig(self.fixture.root,self.fixture.data,self.fixture.root/'dist',server.DB_PATH)
        with TestClient(create_app(config,bridge=self.bridge,agent_factory=None,manage_agent=False),base_url='http://127.0.0.1') as http:
            response=http.post('/api/agent/task',json={'kind':'prepare_practice','paper_id':'paper-test',
                'request_id':str(uuid.uuid4()),'attempt_id':'unrelated-attempt'})
            self.assertEqual(response.status_code,400,response.text)
            self.assertEqual(listing(self.conn),[])
