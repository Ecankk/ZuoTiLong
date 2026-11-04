from app.storage.boundaries import workspace_config,connect_workspace
import json
from pathlib import Path
import unittest
import uuid
from contextlib import closing
from app.knowledge import preparation
from app.learning.tasks import create_task,bind_turn,finish_task,task_record
from app.learning.workflows import mark,reconcile,continue_job


class PreparationRunTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp()
        self.conn=self.f.conn;self.root=self.f.root;self.data=self.f.data

    def tearDown(self):self.f.tearDown()

    def dispatch(self):
        job=dict(self.conn.execute("SELECT * FROM workflow_jobs WHERE status='queued' ORDER BY rowid LIMIT 1").fetchone())
        task=create_task(self.conn,self.root,self.data,job['kind'],None,'same-session',job['request_id'],
                         workflow_id=job['workflow_id'],task_scope=json.loads(job['scope_json']))
        bind_turn(self.conn,task['id'],'same-session',task['run_token'],'turn-'+task['id'])
        self.f.task=task;self.f.lease={'task_id':task['id'],'session_id':'same-session','run_token':task['run_token'],'turn_id':'turn-'+task['id']}
        mark(self.conn,job['id'],'running',task_id=task['id']);self.conn.commit()
        return job

    def finish(self):
        finish_task(self.conn,self.f.task['id']);reconcile(self.conn,self.root,self.data);self.conn.commit()

    def dispatch_through_worker(self,expected_kind):
        import threading,time
        from app.agent.bridge import CodexBridge
        from test_codex_bridge import FakeCodex
        started=threading.Event()
        class Transport(FakeCodex):
            def request(self,method,params):
                value=super().request(method,params)
                if method=='turn/start':started.set()
                return value
        bridge=CodexBridge(self.root,self.data,Transport)
        try:
            bridge.connect()
            self.assertTrue(started.wait(4),bridge.snapshot())
            deadline=time.monotonic()+3
            while time.monotonic()<deadline:
                job=self.conn.execute('SELECT * FROM workflow_jobs WHERE kind=? ORDER BY rowid DESC LIMIT 1',(expected_kind,)).fetchone()
                if job['status']=='running':break
                time.sleep(.01)
            self.assertEqual(job['status'],'running',dict(job))
            task=task_record(self.conn,job['task_id'])
            self.assertEqual(task['kind'],expected_kind)
            self.assertIsNone(task['paper_id'])
            self.assertEqual(json.loads(task['input_json'])['task_scope'],json.loads(job['scope_json']))
            self.assertEqual(sum(name=='turn/start' for name,_ in bridge.transport.calls),1)
            self.assertEqual(bridge._active()['context'],{})
            self.assertEqual(bridge._active().get('agent_prompt',''),'')
            self.assertNotIn('核对整卷可见作答',bridge._active()['inputs'][0]['text'])
        finally:bridge.close()

    def test_real_worker_dispatches_catalogue_with_json_persisted_material_guard(self):
        preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid)
        self.conn.commit()
        self.dispatch_through_worker('maintain_catalog')

    def test_real_worker_dispatches_annotation_with_json_persisted_material_guard(self):
        self.f.prepare_catalog();self.f.seed_questions();self.conn.commit()
        preparation.start(self.conn,self.root,self.data,kind='questions',request_id=str(uuid.uuid4()))
        self.conn.commit()
        self.dispatch_through_worker('annotate_questions')

    def test_pause_blocked_unsent_batch_does_not_wait_for_a_nonexistent_turn(self):
        run=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid)
        rid=run['runs'][0]['id']
        job=self.conn.execute('SELECT id FROM workflow_jobs').fetchone()[0]
        mark(self.conn,job,'blocked','isolated pre-dispatch conflict')
        paused=preparation.action(self.conn,self.root,self.data,rid,'pause')
        self.assertEqual(paused['runs'][0]['status'],'paused')
        self.assertEqual(paused['runs'][0]['counts'],{'queued':1})
        resumed=preparation.action(self.conn,self.root,self.data,rid,'resume')
        self.assertEqual(resumed['runs'][0]['status'],'running')
        self.assertEqual(self.conn.execute('SELECT status FROM workflow_jobs WHERE id=?',(job,)).fetchone()[0],'abandoned')

    def test_resume_uses_later_reviewed_source_instead_of_keeping_stale_pending_count(self):
        run=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid)
        rid=run['runs'][0]['id'];job=self.dispatch()
        self.f.tool('task_context',{'source_ids':['GS-04-001']})
        pending={'summary':'Await mathematical review.','node_changes':[],'redirects':[],
                 'source_resolutions':[{'source_id':'GS-04-001','disposition':'pending','node_ids':[],'reason':'Need review.'}],
                 'limitations':['Unreviewed.']}
        preparation.action(self.conn,self.root,self.data,rid,'pause')
        self.conn.commit()
        self.f.tool('apply_report',{'result':self.f.envelope(pending)});self.finish()
        before=preparation.snapshot(self.conn,rid)['runs'][0]
        self.assertEqual(before['status'],'paused');self.assertEqual(before['counts'],{'needs_review':1})
        self.f.start('maintain_catalog',{'source_version_id':self.f.f.sid,'source_ids':['GS-04-001']})
        self.f.tool('task_context',{'source_ids':['GS-04-001']})
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.maintenance_result())})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        jobs=self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0]
        after=preparation.action(self.conn,self.root,self.data,rid,'resume')['runs'][0]
        self.assertEqual(after['status'],'completed');self.assertEqual(after['counts'],{'completed':1})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],jobs)

    def test_catalogue_then_annotation_automatically_advance_only_after_saved_task_completion(self):
        ids=self.f.seed_questions(aliases=True)
        result=preparation.start(self.conn,self.root,self.data,kind='catalog',source_version_id=self.f.f.sid,
                                 request_id=str(uuid.uuid4()),auto_annotate=True,batch_size=1)
        self.assertEqual(result['runs'][0]['counts'],{'running':1})
        self.assertFalse((self.data/'agent-session.db').exists())
        job=self.dispatch();self.f.tool('task_context',{'source_ids':['GS-04-001']})
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.maintenance_result())})
        self.assertEqual(task_record(self.conn,self.f.task['id'])['status'],'completed')
        continue_job(self.conn,self.root,self.data,job,task_record(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_preparation_runs').fetchone()[0],2)
        self.finish()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_preparation_runs').fetchone()[0],2)
        self.dispatch();self.assertEqual(self.f.task['kind'],'annotate_questions')
        self.f.read_annotation_material();self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        self.finish();state=preparation.snapshot(self.conn)
        self.assertTrue(all(r['status']=='completed' for r in state['runs']))
        self.assertEqual(next(r for r in state['runs'] if r['kind']=='questions')['counts'],{'completed':2})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],1)
        count=self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0]
        reconcile(self.conn,self.root,self.data)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],count)
        for table in ('papers','probe_attempts','learning_events'):
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_existing_ready_question_analyses_are_reused_without_new_agent_task(self):
        ids=self.f.save_annotation()
        count=self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0]
        result=preparation.start(self.conn,self.root,self.data,kind='questions',request_id=str(uuid.uuid4()),item_ids=ids)
        self.assertEqual(result['runs'][0]['status'],'completed')
        self.assertEqual(result['runs'][0]['counts'],{'completed':2})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],count)

    def test_concrete_unreadable_material_is_retained_as_issue_without_looping(self):
        self.f.prepare_catalog();self.f.seed_questions()
        self.conn.execute("UPDATE bank_questions SET stem='',answer=NULL,explanation=NULL");self.conn.commit()
        result=preparation.start(self.conn,self.root,self.data,kind='questions',request_id=str(uuid.uuid4()),batch_size=1)
        self.assertEqual(result['runs'][0]['status'],'needs_review')
        self.assertIn('题干',result['runs'][0]['issues'][0]['note'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],0)

    def test_same_preparation_request_is_idempotent_and_cannot_change_scope(self):
        request=str(uuid.uuid4())
        first=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=request,source_version_id=self.f.f.sid)
        again=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=request,source_version_id=self.f.f.sid)
        self.assertEqual(first['runs'][0]['id'],again['runs'][0]['id'])
        with self.assertRaisesRegex(ValueError,'更换范围'):
            preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=request,source_version_id=self.f.f.sid,batch_size=1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],1)

    def test_pause_unsent_batch_and_resume_keeps_run_and_creates_one_fresh_dispatch(self):
        run=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid)
        rid=run['runs'][0]['id']
        paused=preparation.action(self.conn,self.root,self.data,rid,'pause')
        self.assertEqual(paused['runs'][0]['status'],'paused')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM workflow_jobs WHERE status='queued'").fetchone()[0],0)
        continued=preparation.action(self.conn,self.root,self.data,rid,'resume')
        self.assertEqual(continued['runs'][0]['id'],rid)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM workflow_jobs WHERE status='queued'").fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],0)

    def test_pause_during_current_turn_finishes_safely_without_dispatching_next_stage(self):
        self.f.seed_questions()
        run=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid,auto_annotate=True)
        rid=run['runs'][0]['id'];self.dispatch()
        state=preparation.action(self.conn,self.root,self.data,rid,'pause');self.conn.commit()
        self.assertEqual(state['runs'][0]['status'],'pausing')
        self.f.tool('task_context',{'source_ids':['GS-04-001']})
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.maintenance_result())});self.finish()
        self.assertEqual(preparation.snapshot(self.conn,rid)['runs'][0]['status'],'paused')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_preparation_runs').fetchone()[0],1)
        preparation.action(self.conn,self.root,self.data,rid,'resume')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_preparation_runs').fetchone()[0],2)

    def test_http_status_and_pause_remain_available_during_owned_agent_turn(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from test_fastapi_app import OwnedAgent
        run=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid)
        self.conn.commit()
        owner=OwnedAgent(self.root,self.data);owner.busy=True
        with TestClient(create_app(self.f.f.config,bridge=owner),base_url='http://127.0.0.1') as http:
            response=http.get('/api/agent/state')
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['knowledge_preparation'][0]['total'],1)
            self.assertEqual(http.post('/api/knowledge/preparation/start',json={'kind':'catalog','source_version_id':self.f.f.sid,'request_id':str(uuid.uuid4())}).status_code,409)
            response=http.post('/api/knowledge/preparation/'+run['runs'][0]['id']+'/action',json={'operation':'pause'})
            self.assertEqual(response.status_code,200)
            self.assertEqual(response.json()['runs'][0]['status'],'paused')

    def test_restore_retry_relinks_the_same_run_to_fresh_execution(self):
        from app.storage.maintenance import backup,restore
        from app.agent.bridge import CodexBridge
        from app.config import AppConfig
        from app.storage.database import Database
        run=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.f.f.sid)
        self.conn.commit();archive=backup(self.data,self.root)
        target=self.data/'restored';restore(Path(archive['path']),target)
        Database(workspace_config(target,self.root)).initialize()
        bridge=CodexBridge(self.root,target)
        try:
            with closing(bridge._learning_connection()) as conn:
                old=dict(conn.execute('SELECT * FROM workflow_jobs').fetchone())
                self.assertTrue(old['recovery_required'])
            bridge.workflow_action(old['id'],'retry')
            with closing(bridge._learning_connection()) as conn:
                item=conn.execute('SELECT * FROM knowledge_preparation_items').fetchone()
                current=conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(item['job_id'],)).fetchone()
                self.assertNotEqual(current['id'],old['id'])
                self.assertEqual(current['workflow_id'],run['runs'][0]['id'])
                self.assertEqual(current['status'],'queued')
                self.assertEqual(json.loads(current['scope_json'])['source_ids'],['GS-04-001'])
        finally:bridge.close()
