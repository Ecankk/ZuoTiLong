import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
from unittest.mock import patch
from contextlib import closing

from fastapi.testclient import TestClient
from app.agent.session_store import SessionStore
from app.main import create_app

ROOT=Path(__file__).resolve().parents[1]


class SessionStateTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='state-version-')
        self.path=Path(self.temp.name)/'session.db'
        self.store=SessionStore(self.path)
    def tearDown(self):self.temp.cleanup()

    def test_clean_and_legacy_sessions_have_monotone_persisted_versions(self):
        state=self.store.load()
        self.assertEqual(state['revision'],0)
        state['session_id']='existing-session'
        self.store.save(state);first=state['revision']
        state['status']='running';self.store.save(state)
        self.assertGreater(state['revision'],first)
        loaded=SessionStore(self.path).load()
        self.assertEqual(loaded,state)
        legacy={k:v for k,v in loaded.items() if k!='revision'}
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute('UPDATE session SET payload=?',(json.dumps(legacy),))
        self.assertEqual(self.store.load()['revision'],0)
        self.store.save(legacy)
        self.assertEqual(legacy['session_id'],'existing-session')
        self.assertIsInstance(legacy['revision'],int)

    def test_stale_writer_cannot_reset_version_and_failed_save_does_not_advance_it(self):
        first=self.store.load();other=dict(first)
        self.store.save(first);self.store.save(other)
        self.assertGreater(other['revision'],first['revision'])
        before=dict(other)
        with closing(sqlite3.connect(self.path)) as conn,conn:
            conn.execute("CREATE TRIGGER reject_save BEFORE INSERT ON session BEGIN SELECT RAISE(ABORT,'isolated failure'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.store.save(other)
        self.assertEqual(other,before)
        self.assertEqual(self.store.load(),before)


class PublicAgentStateTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        self.fixture=KnowledgeCatalogTests();self.fixture.setUp()
        self.fixture.conn.commit()
    def tearDown(self):self.fixture.tearDown()

    @patch('app.agent.bridge.CodexBridge.ensure_connection', return_value=None)
    def test_clean_disconnected_state_tracks_external_preparation_changes_without_connecting(self, _connection):
        f=self.fixture
        with TestClient(create_app(f.config),base_url='http://127.0.0.1') as http:
            first=http.get('/api/agent/state').json()
            self.assertIsInstance(first['revision'],int)
            self.assertFalse(first['connected']);self.assertIsNone(first['session_id'])
            response=http.post('/api/knowledge/preparation/start',json={
                'kind':'catalog','request_id':str(uuid.uuid4()),'source_version_id':f.sid})
            self.assertEqual(response.status_code,200,response.text)
            run=response.json()['runs'][0]['id']
            running=http.get('/api/agent/state').json()
            self.assertGreater(running['snapshot_sequence'],first['snapshot_sequence'])
            self.assertEqual(running['revision'],first['revision'])
            for operation,expected in [('pause','paused'),('resume','running')]:
                response=http.post('/api/knowledge/preparation/'+run+'/action',json={'operation':operation})
                self.assertEqual(response.status_code,200,response.text)
                current=http.get('/api/agent/state').json()
                self.assertEqual(current['snapshot_epoch'],first['snapshot_epoch'])
                self.assertGreater(current['snapshot_sequence'],running['snapshot_sequence'])
                self.assertEqual(current['knowledge_preparation'][0]['status'],expected)
                running=current
            bridge=http.app.state.runtime.bridge
            self.assertIsNone(bridge.transport)
            self.assertIsNone(running['session_id'])
        with TestClient(create_app(f.config),base_url='http://127.0.0.1') as http:
            restarted=http.get('/api/agent/state').json()
            self.assertNotEqual(restarted['snapshot_epoch'],first['snapshot_epoch'])
            self.assertIsNone(restarted['session_id'])

    def test_action_response_and_no_agent_snapshot_share_the_public_version_contract(self):
        from unittest.mock import patch
        with TestClient(create_app(self.fixture.config),base_url='http://127.0.0.1') as http:
            bridge=http.app.state.runtime.bridge
            before=http.get('/api/agent/state').json()
            with patch.object(bridge,'interrupt',return_value=bridge.snapshot()):
                response=http.post('/api/agent/interrupt',json={})
            self.assertEqual(response.status_code,200,response.text)
            after=response.json()
            self.assertEqual(before['snapshot_epoch'],after['snapshot_epoch'])
            self.assertGreater(after['snapshot_sequence'],before['snapshot_sequence'])
            self.assertIn('knowledge_preparation',after)
        with TestClient(create_app(self.fixture.config,agent_factory=None),base_url='http://127.0.0.1') as http:
            state=http.get('/api/agent/state').json()
            self.assertEqual(state['revision'],0)
            self.assertEqual(state['status'],'disconnected')


if __name__=='__main__':unittest.main()
