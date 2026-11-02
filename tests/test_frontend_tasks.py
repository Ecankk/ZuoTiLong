import asyncio
import json
import time
import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from starlette.requests import Request

import database_fixture as server
import test_learning_loop as fixtures
from test_codex_bridge import FakeCodex
from app.agent.bridge import CodexBridge
from app.config import AppConfig
from app.documents.progress import write_progress
from app.main import create_app


class LoggedCodex(FakeCodex):
    def request(self, method, params):
        if method == 'account/read':
            self.calls.append((method, params))
            return {'account': {'type': 'chatgpt'}}
        return super().request(method, params)


def wait_for(predicate):
    deadline = time.monotonic()+5
    while not predicate():
        if time.monotonic() > deadline:raise AssertionError('background transition timed out')
        time.sleep(.01)


class FrontendTasksTests(unittest.TestCase):
    def setUp(self):
        self.f = fixtures.LearningLoopTests(); self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.config = AppConfig(server.ROOT, server.DATA, server.DIST, server.DB_PATH)

    def app(self, **kw):
        app = create_app(self.config, agent_factory=None, **kw)
        self.addCleanup(app.state.runtime.close)
        return app

    def bridge(self, transport=LoggedCodex):
        bridge = CodexBridge(self.config.root, self.config.data, transport)
        bridge.learning_db = self.config.database
        self.addCleanup(bridge.close)
        return bridge

    def queue(self, bridge):
        return bridge.queue_task('analyze_paper', 'paper-test', str(uuid.uuid4()))

    def test_tasks_are_paginated_and_actions_are_fenced(self):
        bridge = self.bridge(); app = self.app(bridge=bridge, manage_agent=False)
        self.queue(bridge)
        with TestClient(app, base_url='http://127.0.0.1') as http:
            result = http.get('/api/tasks?limit=1')
            self.assertEqual(result.status_code, 200)
            data = result.json(); item = data['items'][0]
            self.assertEqual(item['status'], 'queued'); self.assertEqual(item['allowed_actions'], ['cancel'])
            self.assertEqual(data['queued_count'], 1)
            for forbidden in ('run_token', 'session_id', 'guard_json', 'messages', 'input_json'):
                self.assertNotIn(forbidden, result.text)
            self.assertEqual(http.get('/api/tasks', headers={'If-None-Match': result.headers['etag']}).status_code, 200)  # different limit
            self.assertEqual(http.get('/api/tasks?limit=1', headers={'If-None-Match': result.headers['etag']}).status_code, 304)
            self.assertEqual(http.post('/api/tasks/'+item['id']+'/action', json={'action': 'retry'}).status_code, 409)
            response = http.post('/api/tasks/'+item['id']+'/action', json={'action': 'cancel'})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()['items'][0]['status'], 'cancelled')
            self.assertEqual(http.post('/api/tasks/missing/action', json={'action': 'cancel'}).status_code, 404)
            self.assertEqual(http.get('/api/tasks?status=invalid').status_code, 400)
            self.assertEqual(http.get('/api/tasks?limit=101').status_code, 400)

    def test_missing_executable_is_identified_without_spawning_or_consuming_queue(self):
        bridge = self.bridge(); app = self.app(bridge=bridge, manage_agent=False)
        self.queue(bridge)
        from app.agent.transport import CodexProcess
        bridge.transport_factory = CodexProcess
        bridge.auto_connect = True
        with patch('app.agent.transport.codex_executable', return_value=None), patch('app.agent.transport.subprocess.Popen') as process:
            bridge.ensure_connection()
            wait_for(lambda: not bridge.connecting and bridge.unavailable_reason == 'not_installed')
            data = app.state.runtime.tasks.read()
            self.assertEqual(data['status'], 'agent_unavailable')
            self.assertEqual(data['availability']['reason'], 'not_installed')
            self.assertEqual(data['items'][0]['status'], 'queued')
            self.assertEqual(self.f.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0], 0)
            process.assert_not_called()

    def test_not_logged_in_is_separate_from_other_failure_and_can_recheck(self):
        class NotLogged(FakeCodex):
            instances = []
            def __init__(self, *args):
                super().__init__(*args); self.instances.append(self)
        bridge = self.bridge(NotLogged); app = self.app(bridge=bridge, manage_agent=False)
        self.queue(bridge); bridge.auto_connect = True; bridge.ensure_connection()
        wait_for(lambda: not bridge.connecting and bridge.unavailable_reason == 'not_logged_in')
        data = app.state.runtime.tasks.read()
        self.assertEqual(data['availability']['reason'], 'not_logged_in')
        self.assertEqual(data['queued_count'], 1)
        self.assertFalse(any(m in ('model/list', 'thread/start', 'thread/resume', 'turn/start') for m,p in NotLogged.instances[0].calls))
        bridge.transport_factory = LoggedCodex; bridge.next_connect_check = 0
        bridge.ensure_connection()
        wait_for(lambda: bridge.connected and bridge._active() and bridge._active().get('codex_turn_id'))
        self.assertEqual(app.state.runtime.tasks.read()['status'], 'running')
        self.assertEqual(app.state.runtime.tasks.read()['availability']['status'], 'available')

    def test_other_connection_failure_does_not_look_like_login_or_installation(self):
        def broken(*a):raise RuntimeError('transport broken')
        bridge = self.bridge(broken); app = self.app(bridge=bridge, manage_agent=False)
        self.queue(bridge); bridge.auto_connect = True; bridge.ensure_connection()
        wait_for(lambda: not bridge.connecting and bridge.unavailable_reason == 'other')
        self.assertEqual(app.state.runtime.tasks.read()['availability']['reason'], 'other')

    def test_runtime_automatically_connects_only_for_pending_work_and_resumes_same_turn(self):
        made = []
        def factory(root, data):
            bridge = CodexBridge(root, data, LoggedCodex); made.append(bridge); return bridge
        app = create_app(self.config, agent_factory=factory)
        with TestClient(app, base_url='http://127.0.0.1') as http:
            bridge = made[0]
            self.assertIsNone(bridge.transport)
            response = http.post('/api/agent/task', json={'kind': 'analyze_paper', 'paper_id': 'paper-test', 'request_id': str(uuid.uuid4())})
            self.assertEqual(response.status_code, 200, response.text)
            wait_for(lambda: bridge._active() and bridge._active().get('codex_turn_id'))
            original = bridge._active().copy()
            summary = http.get('/api/tasks').json()
            self.assertIn('正在分析《test》', summary['active']['progress']['message'])
            self.assertEqual(summary['active']['allowed_actions'], [])
        class Resume(LoggedCodex):
            def __init__(self, *args):
                super().__init__(*args)
                self.history = [{'id': original['codex_turn_id'], 'status': 'inProgress'}]
        second = create_app(self.config, agent_factory=lambda r,d: CodexBridge(r,d,Resume))
        with TestClient(second, base_url='http://127.0.0.1'):
            resumed = second.state.runtime.bridge
            wait_for(lambda: resumed.connected)
            self.assertEqual(resumed._active()['task_id'], original['task_id'])
            self.assertEqual(resumed._active()['codex_turn_id'], original['codex_turn_id'])
            self.assertEqual(self.f.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0], 1)
            self.assertFalse(any(m in ('thread/start', 'turn/start') for m,p in resumed.transport.calls))

    def test_restored_and_released_work_is_not_automatically_replayed(self):
        bridge = self.bridge(); self.queue(bridge)
        self.f.conn.execute('UPDATE workflow_jobs SET recovery_required=1'); self.f.conn.commit()
        bridge.auto_connect = True; bridge.ensure_connection()
        self.assertIsNone(bridge.transport)
        self.f.conn.execute('UPDATE workflow_jobs SET recovery_required=0'); self.f.conn.commit()
        bridge.state['external_control'] = True
        bridge.ensure_connection(); self.assertIsNone(bridge.transport)

    def test_failed_task_action_reconciles_and_retries_the_same_task(self):
        bridge=self.bridge();app=self.app(bridge=bridge,manage_agent=False)
        bridge.connect();wait_for(lambda:bridge.connected)
        self.queue(bridge)
        wait_for(lambda:bridge._active() and bridge._active().get('codex_turn_id'))
        original=bridge._active().copy()
        bridge.event({'method':'turn/completed','params':{'threadId':bridge.state['session_id'],
            'turnId':original['codex_turn_id'],'turn':{'id':original['codex_turn_id'],'status':'failed'}}})
        bridge.transport.history=[{'id':original['codex_turn_id'],'status':'failed'}]
        calls=len(bridge.transport.calls)
        from app.agent.errors import BridgeConflict
        with self.assertRaises(BridgeConflict):bridge.retry(expected_task_id='another-task')
        self.assertEqual(len(bridge.transport.calls),calls)
        with TestClient(app,base_url='http://127.0.0.1') as http:
            item=http.get('/api/tasks').json()['active']
            self.assertEqual(item['allowed_actions'],['retry'])
            result=http.post('/api/tasks/'+item['id']+'/action',json={'action':'retry'})
            self.assertEqual(result.status_code,200,result.text)
            wait_for(lambda:bridge._active().get('codex_turn_id') not in (None,original['codex_turn_id']))
            self.assertEqual(bridge._active()['task_id'],original['task_id'])
            self.assertEqual(self.f.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],1)

    def test_auto_resume_checks_saved_receipt_before_starting_child(self):
        from test_study_workflows import WorkflowTests
        case=WorkflowTests();case.setUp();self.addCleanup(case.tearDown)
        case.queue_analysis();case.save_analysis()
        original=case.bridge._active().copy();case.bridge.close()
        class SavedRemote(LoggedCodex):
            def __init__(self,*args):
                super().__init__(*args)
                self.history=[{'id':original['codex_turn_id'],'status':'completed'}]
        config=AppConfig(server.ROOT,server.DATA,server.DIST,server.DB_PATH)
        app=create_app(config,agent_factory=lambda r,d:CodexBridge(r,d,SavedRemote))
        with TestClient(app,base_url='http://127.0.0.1'):
            case.bridge=app.state.runtime.bridge
            wait_for(lambda:case.bridge._active() and case.bridge._active().get('task_kind')=='prepare_practice')
            self.assertEqual(case.fixture.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],1)
            self.assertEqual(case.fixture.conn.execute("SELECT count(*) FROM learning_tasks WHERE kind='analyze_paper'").fetchone()[0],1)
            self.assertFalse(any(m=='thread/start' for m,p in case.bridge.transport.calls))
            task=case.fixture.conn.execute('SELECT status FROM learning_tasks WHERE id=?',(original['task_id'],)).fetchone()
            self.assertEqual(task[0],'completed')

    def test_sse_snapshot_reconnect_and_coalesced_resource_and_preparation_changes(self):
        app = self.app(); rt = app.state.runtime
        rt.events.poll()
        async def receive():return {'type': 'http.request', 'body': b'', 'more_body': False}
        def request(last=None):
            return Request({'type': 'http', 'method': 'GET', 'path': '/api/events',
                            'headers': [(b'last-event-id', last.encode())] if last else []}, receive)
        async def check():
            stream = rt.events.stream(request())
            first = await anext(stream)
            self.assertIn('event: snapshot', first)
            self.assertIn('"availability"', first)
            self.assertNotIn('run_token', first)
            old_id = next(line[4:] for line in first.splitlines() if line.startswith('id: '))
            rt.papers.create({'title':'new saved paper'})
            write_progress(self.config.data, 'paper-test', status='running', phase='opening', message='正在读取试卷', pages_done=1, pages_total=2)
            rt.events.poll()
            prep = await anext(stream); resource = await anext(stream)
            self.assertIn('event: preparation.changed', prep)
            self.assertIn('event: resources.changed', resource)
            await stream.aclose()
            reconnect = rt.events.stream(request(old_id))
            again = await anext(reconnect)
            self.assertIn('event: snapshot', again)
            self.assertIn('正在读取试卷', again)
            new_id = next(line[4:] for line in again.splitlines() if line.startswith('id: '))
            self.assertNotEqual(old_id, new_id)
            await reconnect.aclose()
        asyncio.run(check())

    def test_sse_http_boundary_headers_and_unavailable_snapshot(self):
        app = self.app(); rt = app.state.runtime
        rt.events.poll()
        original = rt.events.stream
        async def first_only(request):
            stream = original(request)
            try:yield await anext(stream)
            finally:await stream.aclose()
        with patch.object(rt.events, 'stream', first_only):
            http = TestClient(app, base_url='http://127.0.0.1'); self.addCleanup(http.close)
            denied = http.get('/api/events', headers={'Origin':'https://foreign.example'})
            self.assertEqual(denied.status_code, 403)
            response = http.get('/api/events', headers={'Last-Event-ID':'old-epoch:100'})
            self.assertEqual(response.status_code, 200)
            self.assertIn('text/event-stream', response.headers['content-type'])
            self.assertEqual(response.headers['cache-control'], 'no-store')
            self.assertEqual(response.headers['x-accel-buffering'], 'no')
            self.assertIn('event: snapshot', response.text)
            self.assertIn('agent_unavailable', response.text)

    def test_sse_task_change_does_not_emit_chat_and_errors_close_cleanly(self):
        bridge = self.bridge(); app = self.app(bridge=bridge, manage_agent=False); rt = app.state.runtime
        rt.events.poll()
        async def receive():return {'type':'http.request', 'body':b'', 'more_body':False}
        async def check():
            stream = rt.events.stream(Request({'type':'http', 'headers':[]}, receive))
            await anext(stream)
            self.queue(bridge); rt.events.poll()
            frame = await anext(stream)
            self.assertIn('event: tasks.changed', frame)
            self.assertNotIn('inputs', frame); self.assertNotIn('session_id', frame)
            await stream.aclose()
            rt.events.error = True
            broken = rt.events.stream(Request({'type':'http', 'headers':[]}, receive))
            self.assertIn('event: error', await anext(broken))
            with self.assertRaises(StopAsyncIteration):await anext(broken)
        asyncio.run(check())

    def test_real_asgi_sse_disconnect_releases_the_stream(self):
        app=self.app();app.state.runtime.events.poll()
        async def check():
            inbox=asyncio.Queue();await inbox.put({'type':'http.request','body':b'','more_body':False})
            sent=[]
            async def receive():return await inbox.get()
            async def send(message):
                sent.append(message)
                if message['type']=='http.response.body' and b'event: snapshot' in message.get('body',b''):
                    await inbox.put({'type':'http.disconnect'})
            scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.0'},'http_version':'1.1',
                   'method':'GET','scheme':'http','path':'/api/events','raw_path':b'/api/events','root_path':'',
                   'query_string':b'','headers':[(b'host',b'127.0.0.1')],
                   'server':('127.0.0.1',80),'client':('127.0.0.1',3000)}
            await asyncio.wait_for(app(scope,receive,send),timeout=3)
            self.assertEqual(sent[0]['status'],200)
            self.assertTrue(any(b'event: snapshot' in m.get('body',b'') for m in sent))
        asyncio.run(check())

    def test_failed_startup_closes_observer_handles(self):
        app=self.app();rt=app.state.runtime
        self.f.conn.close()
        def fail():
            rt.workspace.revision()
            raise RuntimeError('isolated startup failure')
        with patch.object(rt.events,'poll',side_effect=fail):
            with self.assertRaisesRegex(RuntimeError,'isolated startup failure'):
                with TestClient(app,base_url='http://127.0.0.1'):pass
        # Windows refuses this rename if either read observer was left open.
        self.config.library_database.rename(self.config.library_dir/'closed-library.db')
