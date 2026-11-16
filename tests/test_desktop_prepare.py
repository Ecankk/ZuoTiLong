from contextlib import closing
import io,json,os,sqlite3,tempfile,threading,unittest
from pathlib import Path
from unittest.mock import patch
from types import SimpleNamespace
import desktop_fixture as fixture
from app.desktop.config import settings
from app.desktop.protocol import Protocol,DesktopError,Cancelled
from app.desktop.prepare import prepare
from app.desktop.control import CANCEL


class DesktopPrepareTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.root=fixture.resources(self.base);self.args=fixture.arguments(self.base,self.root)
        self.decoy=self.base/'继承诱饵'
        self.patcher=patch.dict(os.environ,dict(MATHLENS_DATA_DIR=str(self.decoy/'data'),MATHLENS_LIBRARY_DIR=str(self.decoy/'library'),MATHLENS_DIST_DIR=str(self.decoy/'dist'),MATHLENS_DEMO='1'))
        self.patcher.start();self.addCleanup(self.patcher.stop)

    def run_prepare(self):
        stream=io.StringIO();config=settings(self.args)
        result=prepare(config,Protocol('prepare',self.args.launch_nonce,stream))
        self.assertFalse(self.decoy.exists());return config,result,[json.loads(x) for x in stream.getvalue().splitlines()]

    def test_explicit_paths_verified_publish_empty_workspace_and_reuse(self):
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        config,result,events=self.run_prepare();self.assertFalse(config.demo);self.assertFalse(result['reused_library'])
        self.assertFalse((Path(self.args.library_dir).parent/'.mathlens-prepare.lock').exists())
        self.assertEqual(events[-1]['event'],'prepared');self.assertEqual([e['seq'] for e in events],list(range(1,len(events)+1)))
        self.assertTrue(all(e['nonce']==self.args.launch_nonce for e in events))
        self.assertEqual({p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()},before)
        self.assertFalse(list(self.base.rglob('desktop.json')))
        self.assertEqual(json.loads((config.data/'workspace.json').read_text(encoding='utf8'))['library'],'../../library')
        with closing(sqlite3.connect(config.database)) as conn:
            for table in ('papers','questions','probe_attempts','profile_practice_attempts','free_practice_attempts','workflow_jobs','bank_views','learning_tasks'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0,table)
        before=config.library_database.read_bytes()
        self.assertTrue(self.run_prepare()[1]['reused_library']);self.assertEqual(config.library_database.read_bytes(),before)

    def test_bad_seed_staging_cancel_and_disk_full_do_not_publish(self):
        seed=self.root/'library-seed';(seed/'bank-assets/question.png').write_bytes(b'wrong')
        with self.assertRaisesRegex(DesktopError,'大小|散列'):self.run_prepare()
        self.assertFalse(Path(self.args.library_dir).exists())
        fixture.refresh_manifest(self.root)
        with patch('app.desktop.prepare.shutil.disk_usage',return_value=SimpleNamespace(free=0)):
            with self.assertRaisesRegex(DesktopError,'空间不足'):self.run_prepare()
        stop=threading.Event();token=CANCEL.set(stop)
        original=Protocol.progress
        def progress(obj,phase,*a,**kw):
            original(obj,phase,*a,**kw)
            if phase=='copy_seed':stop.set()
        try:
            with patch.object(Protocol,'progress',progress):
                with self.assertRaises(Cancelled):self.run_prepare()
        finally:CANCEL.reset(token)
        self.assertFalse(Path(self.args.library_dir).exists());self.assertFalse(list(self.base.rglob('library.staging-*')))
        self.assertFalse((Path(self.args.library_dir).parent/'.mathlens-prepare.lock').exists())

    def test_failed_workspace_initialization_retains_published_library_and_retry(self):
        from app.storage.database import Database
        with patch.object(Database,'initialize',side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(RuntimeError):self.run_prepare()
        self.assertTrue((Path(self.args.library_dir)/'library.db').is_file())
        self.assertFalse((Path(self.args.library_dir).parent/'.mathlens-prepare.lock').exists())
        self.assertTrue(self.run_prepare()[1]['reused_library'])

    def test_invalid_paths_existing_incomplete_and_seed_allowlist(self):
        self.args.data_dir='relative'
        with self.assertRaises(DesktopError):settings(self.args)
        self.assertFalse(self.decoy.exists());self.args=fixture.arguments(self.base,self.root)
        library=Path(self.args.library_dir);library.mkdir(parents=True);(library/'unrelated').write_text('keep')
        with self.assertRaisesRegex(DesktopError,'不完整'):self.run_prepare()
        self.assertEqual((library/'unrelated').read_text(),'keep')
        (library/'unrelated').unlink();library.rmdir()
        (self.root/'library-seed/private.log').write_text('not allowed')
        with self.assertRaisesRegex(DesktopError,'清单'):self.run_prepare()

    def test_workspace_with_personal_history_without_marker_is_never_reinitialized(self):
        config,_,_=self.run_prepare()
        with closing(sqlite3.connect(config.database)) as conn,conn:conn.execute("INSERT INTO papers(id,title,created_at) VALUES('saved','saved','now')")
        (config.data/'workspace.json').unlink()
        with self.assertRaisesRegex(DesktopError,'个人记录'):self.run_prepare()
        with closing(sqlite3.connect(config.database)) as conn:self.assertEqual(conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)

    def test_empty_interrupted_workspace_can_resume_but_session_without_marker_cannot(self):
        config,_,_=self.run_prepare();(config.data/'workspace.json').unlink()
        self.assertTrue(self.run_prepare()[1]['workspace_ready'])
        (config.data/'workspace.json').unlink();(config.data/'agent-session.db').touch()
        with self.assertRaisesRegex(DesktopError,'已有会话'):self.run_prepare()

    def test_manifest_ready_counts_database_corruption_and_lock_reject(self):
        manifest=self.root/'library-seed/manifest.json';value=json.loads(manifest.read_text(encoding='utf8'))
        value['counts']['ready']=1;value['collections'][0]['ready']=1;manifest.write_text(json.dumps(value),encoding='utf8')
        with self.assertRaisesRegex(DesktopError,'标注计数'):self.run_prepare()
        self.assertFalse(list(self.base.rglob('library.staging-*')))
        fixture.refresh_manifest(self.root)
        from app.desktop.prepare import prepare_lock
        with prepare_lock(Path(self.args.library_dir).parent):
            with self.assertRaisesRegex(DesktopError,'另一个进程'):self.run_prepare()
        (self.root/'library-seed/library.db').write_bytes(b'not sqlite')
        # A corrupt DB with an honest byte manifest must still fail SQLite checks.
        value=json.loads(manifest.read_text(encoding='utf8'));raw=b'not sqlite'
        import hashlib
        value['files']['library.db']=dict(size=len(raw),sha256=hashlib.sha256(raw).hexdigest());manifest.write_text(json.dumps(value),encoding='utf8')
        with self.assertRaises(DesktopError) as caught:self.run_prepare()
        self.assertEqual(caught.exception.code,'seed_db_invalid')

    def test_stale_unheld_lock_is_reclaimed_and_deleted(self):
        parent=Path(self.args.library_dir).parent;parent.mkdir(parents=True,exist_ok=True)
        lock=parent/'.mathlens-prepare.lock';lock.write_bytes(b'stale')
        self.assertTrue(self.run_prepare()[1]['workspace_ready']);self.assertFalse(lock.exists())
