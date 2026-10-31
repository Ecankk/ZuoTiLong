import json
import time
import unittest
import uuid
from contextlib import closing

import test_task_bridge as bridge_tests
from test_codex_bridge import FakeCodex
from app.agent.bridge import CodexBridge, BridgeConflict
from app.learning.tasks import task_record, deliver, finish_task
from app.learning.loop import submit_probe, supplement_attempt
from app.learning.workflows import enqueue, listing, reconcile
import database_fixture as server


class WorkflowTests(unittest.TestCase):
    setUp = bridge_tests.TaskBridgeTests.setUp
    tearDown = bridge_tests.TaskBridgeTests.tearDown
    wait = bridge_tests.TaskBridgeTests.wait
    call = bridge_tests.TaskBridgeTests.call
    end = bridge_tests.TaskBridgeTests.end

    def queue_analysis(self):
        self.bridge.queue_task('analyze_paper', 'paper-test', str(uuid.uuid4()), auto_prepare=True)
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('codex_turn_id'))
        self.fixture.kind = 'analyze_paper'
        self.fixture.task = task_record(self.fixture.conn, self.bridge._active()['task_id'])

    def test_new_api_pipeline_indexes_only_after_saved_practice_and_remote_completion(self):
        from app.knowledge.index import snapshot
        self.bridge.queue_task('analyze_paper','paper-test',str(uuid.uuid4()),auto_prepare=True,index_after=True)
        self.wait(lambda:self.bridge._active() and self.bridge._active().get('codex_turn_id'))
        self.fixture.kind='analyze_paper';self.fixture.task=task_record(self.fixture.conn,self.bridge._active()['task_id'])
        self.save_analysis();self.end()
        self.wait(lambda:self.bridge._active() and self.bridge._active().get('task_kind')=='prepare_practice' and self.bridge._active().get('codex_turn_id'))
        self.fixture.kind='prepare_practice';self.fixture.task=task_record(self.fixture.conn,self.bridge._active()['task_id'])
        value=self.fixture.envelope({'goals':[],'exercises':[],'limitations':['No valuable exercise in this fixture.']})
        ok,saved=self.call('apply_report',{'result':value});self.assertTrue(ok['success'],saved)
        self.assertEqual(self.fixture.conn.execute("SELECT count(*) FROM learning_tasks WHERE kind='organize_knowledge'").fetchone()[0],0)
        self.end()
        self.wait(lambda:self.bridge._active() and self.bridge._active().get('task_kind')=='organize_knowledge' and self.bridge._active().get('codex_turn_id'))
        self.fixture.kind='organize_knowledge';self.fixture.task=task_record(self.fixture.conn,self.bridge._active()['task_id'])
        pending=json.loads(self.fixture.task['input_json'])['knowledge_sources']
        mappings=[]
        for source in pending:
            ok,data=self.call('task_context',{'source_ids':[source['source_id']]});self.assertTrue(ok['success'],data)
            mappings.append({'source_id':source['source_id'],'source_revision':source['source_revision'],
                'topic_ids':['math1.calculus.multiple-integrals'],'reason':'Saved evidence concerns integration regions.',
                'event_topics':[{'event_id':e['id'],'topic_ids':['math1.calculus.multiple-integrals']} for e in source['events']]})
        self.assertIn(f'{len(pending)} / {len(pending)}',self.bridge.state['activity'])
        ok,data=self.call('task_context',{'topic_ids':['math1.calculus.multiple-integrals']})
        self.assertTrue(ok['success'],data)
        ok,data=self.call('apply_report',{'result':self.fixture.envelope({'summary':'Indexed saved evidence.','new_nodes':[],'mappings':mappings,'limitations':[]})})
        self.assertTrue(ok['success'],data);self.end();self.wait(lambda:self.bridge.snapshot()['can_submit'])
        self.assertEqual(self.bridge.state['session_id'],'fixed-test-session')
        self.assertEqual(sum(method=='thread/start' for method,_ in self.bridge.transport.calls),1)
        self.assertEqual(len(self.bridge.state['turns']),3)
        self.assertEqual(snapshot(self.fixture.conn)['pending_sources'],[])

    def save_analysis(self, verified=True):
        self.call('read_paper', {'paper_id': 'paper-test', 'pages': [1]})
        payload = self.fixture.analysis()
        if not verified:
            payload['result']['report']['review'] = {'status': 'needs_review', 'issues': ['work unreadable']}
        ok, result = self.call('apply_report', {'result': payload})
        self.assertTrue(ok['success'], result)

    def offline(self, factory=FakeCodex):
        self.bridge.close()
        self.bridge = CodexBridge(self.fixture.root, self.fixture.data, factory)
        self.bridge.learning_db = server.DB_PATH

    def test_verified_analysis_chains_only_after_remote_completion_on_same_session(self):
        self.queue_analysis(); self.save_analysis()
        self.assertEqual(self.fixture.conn.execute("SELECT count(*) FROM learning_tasks WHERE kind='prepare_practice'").fetchone()[0], 0)
        self.end()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('task_kind') == 'prepare_practice')
        self.assertEqual(self.bridge.state['session_id'], 'fixed-test-session')
        self.assertEqual(sum(m == 'thread/start' for m, _ in self.bridge.transport.calls), 1)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)
        self.assertEqual(len(listing(self.fixture.conn)), 2)
        with self.assertRaises(BridgeConflict):
            self.bridge.assert_user_write_allowed()

    def test_offline_job_survives_restart_and_uses_latest_pre_dispatch_prompt(self):
        self.offline()
        request = str(uuid.uuid4())
        self.bridge.queue_task('analyze_paper', 'paper-test', request, auto_prepare=True)
        self.assertFalse(self.bridge.connected)
        self.assertIsNone(self.bridge.transport)
        self.assertEqual(listing(self.fixture.conn)[0]['status'], 'queued')
        self.offline()
        from app.bank.access import save_agent_prompt
        save_agent_prompt(self.fixture.conn, {'prompt': '蓝色是原作答，绿色是批改。'})
        self.fixture.conn.commit()
        self.bridge.connect()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('codex_turn_id'))
        self.assertEqual(self.bridge._active()['request_id'], request)
        self.assertEqual(self.bridge._active()['agent_prompt'], '蓝色是原作答，绿色是批改。')
        self.assertFalse(any(m == 'thread/start' for m, _ in self.bridge.transport.calls))

    def test_saved_analysis_reconciles_remote_before_creating_child_after_restart(self):
        self.queue_analysis(); self.save_analysis()
        old_id = self.bridge._active()['codex_turn_id']
        def factory(root, data, notify, disconnected):
            transport = FakeCodex(root, data, notify, disconnected)
            transport.history = [{'id': old_id, 'status': 'completed'}]
            return transport
        self.offline(factory)
        self.bridge.connect()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('task_kind') == 'prepare_practice')
        with self.bridge.lock, closing(server.connect()) as conn, conn:
            reconcile(conn, self.fixture.root, self.fixture.data)
            reconcile(conn, self.fixture.root, self.fixture.data)
            self.assertEqual(conn.execute("SELECT count(*) FROM workflow_jobs WHERE kind='prepare_practice'").fetchone()[0], 1)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)

    def test_unverified_analysis_is_readable_without_creating_exercises(self):
        self.queue_analysis(); self.save_analysis(verified=False); self.end()
        self.wait(lambda: self.bridge.snapshot()['can_submit'])
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)
        self.assertEqual(self.fixture.conn.execute("SELECT count(*) FROM workflow_jobs WHERE kind='prepare_practice'").fetchone()[0], 0)

    def test_practice_failure_and_retry_preserve_parent_and_reuse_task(self):
        self.queue_analysis(); self.save_analysis(); self.end()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('task_kind') == 'prepare_practice'
                  and self.bridge._active().get('codex_turn_id'))
        tid = self.bridge._active()['task_id']; remote = self.bridge._active()['codex_turn_id']
        self.end('failed')
        self.bridge.transport.history = [{'id': remote, 'status': 'failed'}]
        self.bridge.retry()
        self.wait(lambda: self.bridge._active().get('codex_turn_id') not in (None, remote))
        self.assertEqual(self.bridge._active()['task_id'], tid)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0], 2)
        self.assertEqual(next(j for j in listing(self.fixture.conn) if j['task_id'] == tid)['status'], 'running')

    def test_changed_pending_material_blocks_instead_of_replaying_and_can_be_cancelled(self):
        self.offline()
        self.bridge.queue_task('analyze_paper', 'paper-test', str(uuid.uuid4()), auto_prepare=True)
        self.fixture.fixture.apply(); self.fixture.conn.commit()
        self.bridge.connect()
        self.wait(lambda: any(j['status'] == 'blocked' for j in self.bridge.snapshot()['workflows']))
        self.assertFalse(self.bridge._active())
        job = listing(self.fixture.conn)[0]
        self.assertIn('版本已改变', job['error'])
        self.bridge.workflow_action(job['id'], 'cancel')
        self.assertEqual(listing(self.fixture.conn)[0]['status'], 'abandoned')
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)

    def test_restored_queue_resumes_only_after_explicit_action_with_fresh_execution(self):
        self.offline()
        self.bridge.queue_task('analyze_paper','paper-test',str(uuid.uuid4()),auto_prepare=True)
        job=listing(self.fixture.conn)[0]
        self.fixture.conn.execute("UPDATE workflow_jobs SET status='blocked',recovery_required=1 WHERE id=?",(job['id'],))
        self.fixture.conn.commit()
        self.bridge.workflow_action(job['id'],'retry')
        jobs=listing(self.fixture.conn)
        self.assertEqual(sorted(j['status'] for j in jobs),['abandoned','queued'])
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],0)
        self.bridge.connect()
        self.wait(lambda:self.bridge._active() and self.bridge._active().get('codex_turn_id'))
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],1)

    def test_pending_job_duplicate_clicks_coalesce_without_creating_session(self):
        self.offline()
        for _ in range(2):
            self.bridge.queue_task('analyze_paper', 'paper-test', str(uuid.uuid4()), auto_prepare=True)
        self.assertEqual(len(listing(self.fixture.conn)), 1)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0], 0)

    def test_saved_receipt_with_failed_remote_turn_never_starts_practice(self):
        self.queue_analysis(); self.save_analysis(); self.end('failed')
        self.assertEqual(listing(self.fixture.conn)[0]['status'], 'failed')
        self.assertEqual(self.fixture.conn.execute("SELECT count(*) FROM workflow_jobs WHERE kind='prepare_practice'").fetchone()[0], 0)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)

    def test_changed_pdf_after_receipt_blocks_continuation_without_erasing_analysis(self):
        self.queue_analysis();self.save_analysis()
        path=self.fixture.fixture.pdf
        path.write_bytes(path.read_bytes()+b'\n')
        self.end()
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],1)
        self.assertEqual(self.fixture.conn.execute("SELECT count(*) FROM learning_tasks WHERE kind='prepare_practice'").fetchone()[0],0)
        job=listing(self.fixture.conn)[0]
        self.assertEqual(job['status'],'blocked')
        self.assertIn('原PDF已改变',job['error'])

    def test_crash_after_task_creation_before_bridge_save_reuses_same_unsent_task(self):
        self.offline()
        from app.learning.tasks import create_task
        request = str(uuid.uuid4())
        job = enqueue(self.fixture.conn, self.fixture.root, self.fixture.data, 'analyze_paper',
                      'paper-test', request, auto_prepare=True)
        task = create_task(self.fixture.conn, self.fixture.root, self.fixture.data, 'analyze_paper',
                           'paper-test', self.bridge.state['session_id'], request, workflow_id=job['workflow_id'])
        self.fixture.conn.execute("UPDATE workflow_jobs SET status='dispatching' WHERE id=?", (job['id'],))
        self.fixture.conn.commit()
        self.bridge.connect()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('codex_turn_id'))
        self.assertEqual(self.bridge._active()['task_id'], task['id'])
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0], 1)
        self.assertEqual(sum(method == 'turn/start' for method, _ in self.bridge.transport.calls), 1)

    def test_missing_bridge_projection_recovers_saved_task_by_actual_remote_id(self):
        self.queue_analysis(); self.save_analysis()
        original = self.bridge._active().copy()
        self.bridge.close()
        # Simulate the session projection lagging behind the authoritative
        # learning DB, rather than deleting the result or forging completion.
        self.bridge.state['active_request'] = None
        self.bridge.state['turns'] = []
        self.bridge._save()
        def factory(root, data, notify, disconnected):
            transport = FakeCodex(root, data, notify, disconnected)
            transport.history = [{'id': original['codex_turn_id'], 'status': 'completed'}]
            return transport
        self.bridge = CodexBridge(self.fixture.root, self.fixture.data, factory)
        self.bridge.learning_db = server.DB_PATH
        self.bridge.connect()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('task_kind') == 'prepare_practice')
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0], 1)
        self.assertEqual(self.fixture.conn.execute('SELECT status FROM learning_tasks WHERE id=?', (original['task_id'],)).fetchone()[0], 'completed')
        self.assertFalse(any(method == 'thread/start' for method, _ in self.bridge.transport.calls))

    def test_retry_lost_failed_projection_reconciles_and_reuses_original_task(self):
        self.queue_analysis()
        original=self.bridge._active().copy()
        self.end('failed')
        self.bridge.transport.history=[{'id':original['codex_turn_id'],'status':'failed'}]
        self.bridge.state['active_request']=None;self.bridge.state['turns']=[]
        self.bridge.state['status']='idle';self.bridge._save()
        job=listing(self.fixture.conn)[0]
        self.bridge.workflow_action(job['id'],'retry')
        self.wait(lambda:self.bridge._active() and self.bridge._active().get('codex_turn_id') not in (None,original['codex_turn_id']))
        self.assertEqual(self.bridge._active()['task_id'],original['task_id'])
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],1)

    def prepare_probe(self):
        self.fixture.apply_analysis()
        self.fixture.start('prepare_practice'); self.fixture.bank_read()
        deliver(self.fixture.conn, self.fixture.root, self.fixture.data, self.fixture.plan(), self.fixture.lease)
        finish_task(self.fixture.conn, self.fixture.task['id']); self.fixture.conn.commit()
        return self.fixture.conn.execute('SELECT id FROM diagnostic_probes').fetchone()[0]

    def test_save_attempt_and_grade_handoff_are_atomic_and_idempotent(self):
        pid = self.prepare_probe(); self.offline()
        body = {'response': 'my handwritten reasoning', 'request_id': str(uuid.uuid4())}
        from app.learning.tasks import atomic
        with self.assertRaisesRegex(ValueError, 'rollback'):
            with atomic(self.fixture.conn):
                attempt = submit_probe(self.fixture.conn, pid, body)
                server.queue_attempt_grading(self.fixture.conn, attempt['attempt_id'])
                raise ValueError('rollback')
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0], 0)
        self.assertEqual(len(listing(self.fixture.conn)), 0)
        for _ in range(2):
            attempt = submit_probe(self.fixture.conn, pid, body)
            server.queue_attempt_grading(self.fixture.conn, attempt['attempt_id'])
            self.fixture.conn.commit()
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0], 1)
        self.assertEqual(len(listing(self.fixture.conn)), 1)
        self.bridge.connect()
        self.wait(lambda: self.bridge._active() and self.bridge._active().get('codex_turn_id'))
        self.assertEqual(self.bridge._active()['attempt_id'], attempt['attempt_id'])
        self.assertEqual(self.bridge._active()['task_kind'], 'grade_attempt')

    def test_supplement_retries_preserve_original_once_and_supersede_unsent_grade(self):
        pid = self.prepare_probe(); self.offline()
        attempt = submit_probe(self.fixture.conn, pid, {'response': 'original'})
        server.queue_attempt_grading(self.fixture.conn, attempt['attempt_id'])
        body = {'response': 'additional step', 'request_id': str(uuid.uuid4())}
        for _ in range(2):
            supplement_attempt(self.fixture.conn, attempt['attempt_id'], body)
            server.queue_attempt_grading(self.fixture.conn, attempt['attempt_id'])
            self.fixture.conn.commit()
        row = self.fixture.conn.execute('SELECT response FROM probe_attempts WHERE id=?', (attempt['attempt_id'],)).fetchone()
        self.assertEqual(row['response'].count('additional step'), 1)
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM record_versions').fetchone()[0], 1)
        self.assertEqual(sorted(j['status'] for j in listing(self.fixture.conn)), ['queued', 'superseded'])
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_events WHERE kind LIKE ?',( 'probe_%',)).fetchone()[0], 0)


if __name__ == '__main__':
    unittest.main()
