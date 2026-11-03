from app.storage.boundaries import workspace_config,connect_workspace
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

import test_learning_loop as fixtures
from app.storage.maintenance import backup, restore
from app.storage.images import save_answer_image, image_path, image_records
from PIL import Image
from io import BytesIO


class LocalRestoreTests(unittest.TestCase):
    def setUp(self):
        self.fixture=fixtures.LearningLoopTests();self.fixture.setUp()

    def tearDown(self):self.fixture.tearDown()

    def test_restore_reads_material_without_old_directory_and_does_not_replay_writer(self):
        f=self.fixture;f.apply()
        raw=BytesIO();Image.new('RGB',(60,40),'white').save(raw,format='PNG')
        image=save_answer_image(f.conn,f.root,raw.getvalue());f.conn.commit()
        path=image_path(image_records(f.conn,[image['id']])[0],f.root)
        state={'session_id':'original-session','active_request':'request-1',
               'turns':[{'request_id':'request-1','status':'running','run_token':'old-ticket',
                         'inputs':[{'type':'localImage','path':str(path)}]}],
               'pending_chain':{'paper_id':'paper-test'}}
        with closing(sqlite3.connect(f.root/'agent-session.db')) as conn,conn:
            conn.execute('CREATE TABLE session(id INTEGER PRIMARY KEY,payload TEXT)')
            conn.execute('INSERT INTO session VALUES(1,?)',(json.dumps(state),))
        (f.root/'server.json').write_text('{"url":"http://127.0.0.1:1"}',encoding='utf8')
        archive=backup(f.root,fixtures.ROOT)['path']
        destination=tempfile.TemporaryDirectory(dir=fixtures.ROOT/'tmp',prefix='restore-test-')
        target=Path(destination.name)/'restored';result=restore(archive,target)
        original=f.root;unavailable=original.with_name(original.name+'-unavailable')
        f.conn.close()
        self.assertEqual(unavailable.resolve().parent,(fixtures.ROOT/'tmp').resolve())
        original.rename(unavailable)
        try:
            with closing(connect_workspace(workspace_config(target),library_write=True)) as conn:
                conn.row_factory=sqlite3.Row
                self.assertTrue((target/conn.execute('SELECT source_path FROM papers').fetchone()[0]).is_file())
                self.assertTrue(image_path(image_records(conn,[image['id']])[0],target).is_file())
                self.assertEqual(conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)
            with closing(sqlite3.connect(target/'agent-session.db')) as conn:
                saved=json.loads(conn.execute('SELECT payload FROM session').fetchone()[0])
            self.assertEqual(saved['session_id'],'original-session')
            self.assertIsNone(saved['active_request'])
            self.assertNotIn('pending_chain',saved)
            self.assertNotIn('run_token',saved['turns'][0])
            self.assertFalse(Path(saved['turns'][0]['inputs'][0]['path']['$file']).is_absolute())
            from app.agent.session_store import SessionStore
            self.assertEqual(SessionStore(target/'agent-session.db').load()['turns'][0]['inputs'][0]['path'],str(target/path.relative_to(f.root)))
            self.assertFalse((target/'server.json').exists())
            self.assertEqual(result['session_policy'],'preserve_id_require_reconnect')
            with self.assertRaises(ValueError):restore(archive,target)
        finally:
            unavailable.rename(original)
            destination.cleanup()

    def test_restore_preserves_pending_jobs_but_requires_explicit_resumption(self):
        import uuid
        from app.learning.workflows import enqueue, listing
        f=self.fixture
        job=enqueue(f.conn,fixtures.ROOT,f.root,'analyze_paper','paper-test',str(uuid.uuid4()),auto_prepare=True)
        f.conn.commit()
        archive=backup(f.root,fixtures.ROOT)['path']
        with tempfile.TemporaryDirectory(dir=fixtures.ROOT/'tmp',prefix='restore-queue-') as folder:
            target=Path(folder)/'restored'
            restore(archive,target)
            with closing(connect_workspace(workspace_config(target),library_write=True)) as db:
                db.row_factory=sqlite3.Row
                saved=listing(db)[0]
                self.assertEqual(saved['id'],job['id'])
                self.assertEqual(saved['status'],'blocked')
                self.assertEqual(saved['recovery_required'],1)
                self.assertIn('资料已恢复',saved['error'])
                self.assertTrue((target/db.execute('SELECT source_path FROM papers').fetchone()[0]).is_file())
