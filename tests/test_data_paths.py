from contextlib import closing
import hashlib,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.config import AppConfig
from app.storage.database import Database
from app.storage.paths import resolve_file
from app.storage.path_upgrade import preview,upgrade,status
from app.bank.access import save_preferences,preferences

class DataPathsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=AppConfig(self.root,self.root/'data',self.root/'dist',self.root/'data'/'learning.db')
        self.db=Database(self.config);self.db.initialize()
        path=self.config.papers/'one.pdf';path.write_bytes(b'invented PDF fixture')
        self.sha=hashlib.sha256(path.read_bytes()).hexdigest()
        with self.db.session(write=True) as conn:
            conn.execute('INSERT INTO papers(id,title,source_path,source_sha256,created_at) VALUES(?,?,?,?,?)',
                         ('one','fixture',str(self.root/'old'/'papers'/'one.pdf'),self.sha,'now'))

    def test_preview_confirmation_backup_and_repeat(self):
        plan=preview(self.config)
        self.assertEqual(len(plan['changes']),1)
        self.assertEqual(plan['changes'][0]['relative'],'papers/one.pdf')
        with self.assertRaises(ValueError):upgrade(self.config,'wrong')
        result=upgrade(self.config,plan['plan_sha256'])
        self.assertTrue(result['applied']);self.assertTrue(Path(result['backup']['path']).is_file())
        self.assertEqual(preview(self.config)['changes'],[])
        self.assertFalse(upgrade(self.config,preview(self.config)['plan_sha256'])['applied'])
        self.assertFalse(status(self.config)['path_migration']['pending'])

    def test_missing_or_changed_file_never_guessed(self):
        (self.config.papers/'one.pdf').write_bytes(b'changed')
        plan=preview(self.config)
        self.assertEqual(plan['changes'],[]);self.assertEqual(len(plan['unresolved']),1)

    def test_invalid_relative_paths_and_symlink_escape(self):
        for path in ('../outside','C:/outside','/outside'):
            with self.assertRaises(ValueError):resolve_file(self.config.data,path)

    def test_partial_preferences_preserve_reserved_and_prompt(self):
        with self.db.session(write=True) as conn:
            save_preferences(conn,dict(study_type=1,reserved=[dict(math_type=1,year='2026')],paper_marking_convention='fixture convention'))
            save_preferences(conn,dict(mask_same_type=False))
            value=preferences(conn)
            self.assertEqual(value['reserved'],[dict(math_type=1,year='2026')])
            self.assertEqual(value['paper_marking_convention'],'fixture convention')

    def test_status_http_is_readonly_and_partial_preferences_http_preserves_state(self):
        from app.main import create_app
        from fastapi.testclient import TestClient
        app=create_app(self.config,agent_factory=None);self.addCleanup(app.state.runtime.close)
        with TestClient(app,base_url='http://127.0.0.1') as http:
            response=http.get('/api/data/status');self.assertEqual(response.status_code,200)
            self.assertTrue(response.json()['path_migration']['pending'])
            self.assertEqual(response.json()['invalid_file_references']['count'],1)
            self.assertEqual(http.post('/api/preferences',json={'reserved':[{'math_type':1,'year':'2026'}]}).status_code,200)
            self.assertEqual(http.post('/api/preferences',json={'mask_same_type':False}).status_code,200)
            self.assertEqual(http.get('/api/preferences').json()['reserved'],[{'math_type':1,'year':'2026'}])

    def test_session_storage_paths_are_relative_and_load_resolves_current_root(self):
        from app.agent.session_store import SessionStore
        store=SessionStore(self.config.data/'agent-session.db');store.load()
        store.save(dict(turns=[dict(inputs=[dict(type='localImage',path=str(self.config.papers/'one.pdf'))])]))
        with closing(__import__('sqlite3').connect(store.path)) as conn:
            raw=conn.execute('SELECT payload FROM session').fetchone()[0]
        self.assertNotIn(str(self.config.data).replace('\\','\\\\'),raw)
        self.assertEqual(store.load()['turns'][0]['inputs'][0]['path'],str(self.config.papers/'one.pdf'))

    def test_explicit_upgrade_of_existing_mutable_session_projection(self):
        from app.agent.session_store import SessionStore
        import sqlite3
        store=SessionStore(self.config.data/'agent-session.db');store.load()
        value=dict(turns=[dict(inputs=[dict(type='localImage',path=str(self.config.papers/'one.pdf'))])])
        with closing(sqlite3.connect(store.path)) as conn,conn:
            conn.execute('INSERT OR REPLACE INTO session VALUES(1,?)',(json.dumps(value),))
        plan=preview(self.config)
        self.assertTrue(any(e['store']=='session' for e in plan['changes']))
        upgrade(self.config,plan['plan_sha256'])
        self.assertEqual(store.load()['turns'],value['turns'])
        self.assertEqual(preview(self.config)['changes'],[])

    def test_nested_library_files_keep_library_ownership(self):
        from app.storage.paths import session_paths
        value={'path':str(self.config.library_dir/'bank-assets'/'fixture.png')}
        packed=session_paths(value,self.config.data)
        self.assertEqual(packed,{'path':{'$file':'bank-assets/fixture.png','root':'library'}})
        self.assertEqual(session_paths(packed,self.config.data,unpack=True),value)
