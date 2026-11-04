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
    setUp=bridge_tests.TaskBridgeTests.setUp
    tearDown=bridge_tests.TaskBridgeTests.tearDown
    wait=bridge_tests.TaskBridgeTests.wait
    call=bridge_tests.TaskBridgeTests.call
    end=bridge_tests.TaskBridgeTests.end

    def offline(self):
        self.bridge.close()
        self.bridge=CodexBridge(self.fixture.root,self.fixture.data,FakeCodex)
        self.addCleanup(self.bridge.close)

    def test_duplicate_queued_requests_coalesce_before_execution(self):
        self.offline()
        for _ in range(2):self.bridge.queue_task('analyze_paper','paper-test',str(uuid.uuid4()),auto_prepare=True)
        self.assertEqual(len(listing(self.fixture.conn)),1)
        self.assertIsNone(self.bridge.state['session_id'])

    def test_changed_pending_material_blocks_without_starting_a_thread(self):
        self.offline();self.bridge.queue_task('analyze_paper','paper-test',str(uuid.uuid4()))
        self.fixture.fixture.pdf.write_bytes(b'changed')
        self.bridge.connect();self.wait(lambda:self.bridge.connected)
        self.bridge._drain_workflows()
        self.assertEqual(listing(self.fixture.conn)[0]['status'],'blocked')
        self.assertFalse(any(m=='thread/start' for m,_ in self.bridge.transport.calls))

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
        self.assertEqual(self.fixture.conn.execute("SELECT count(*) FROM record_versions WHERE kind='attempt'").fetchone()[0], 1)
        self.assertEqual(sorted(j['status'] for j in listing(self.fixture.conn)), ['queued', 'superseded'])
        self.assertEqual(self.fixture.conn.execute('SELECT count(*) FROM learning_events WHERE kind LIKE ?',( 'probe_%',)).fetchone()[0], 0)
