from contextlib import closing
import hashlib,json,sqlite3,tempfile,unittest,zipfile
from pathlib import Path
from unittest.mock import patch

from app.config import AppConfig
from app.storage.database import Database
from app.storage.boundaries import workspace_config
from app.storage.maintenance import backup,restore
from app.storage.library_backup import backup_library,restore_library
from app.storage.backup_archive import file_sha256,snapshot

ROOT=Path(__file__).resolve().parents[1]


class BackupSplitTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp');self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.data=self.base/'workspaces'/'one';self.library=self.base/'library'
        self.config=AppConfig(ROOT,self.data,ROOT/'dist',self.data/'learning.db',library=self.library)
        self.db=Database(self.config);self.db.initialize()
        (self.data/'papers'/'one.pdf').write_bytes(b'isolated original bytes')
        (self.data/'practice-materials').mkdir();(self.data/'practice-materials'/'fixture').write_bytes(b'frozen bytes')
        for name in ('bank-assets/q.png','knowledge-sources/source/index.json'):
            path=self.library/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(name.encode())
        with self.db.session(write=True,library_write=True) as conn:
            conn.execute("INSERT INTO papers(id,title,source_path,created_at) VALUES('p','fixture','papers/one.pdf','now')")
            conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('q','isolated','synthetic','now')")
            conn.execute("INSERT INTO bank_resources VALUES('q','{}','bank-assets/q.png',NULL,NULL)")
        from app.agent.session_store import SessionStore
        store=SessionStore(self.data/'agent-session.db');store.load()
        store.save(dict(session_id=None,turns=[],active_request=None,status='disconnected'))

    def test_personal_snapshot_excludes_library_and_restores_with_matching_identity(self):
        before=file_sha256(self.config.library_database)
        saved=backup(self.data,ROOT)
        with zipfile.ZipFile(saved['path']) as archive:
            manifest=json.loads(archive.read('backup-manifest.json'))
            self.assertTrue({'learning.db','agent-session.db','papers/one.pdf','practice-materials/fixture'}.issubset(archive.namelist()))
            self.assertFalse(any(n.startswith(('__library__/','bank-assets/','knowledge-sources/','library/')) or n=='library.db' for n in archive.namelist()))
            self.assertEqual(manifest['library']['scheme'],'mathlens.library-identity/v1')
        target=self.base/'restored';restore(saved['path'],target)
        self.assertEqual(workspace_config(target).library_dir,self.library)
        self.assertEqual((target/'practice-materials'/'fixture').read_bytes(),b'frozen bytes')
        with closing(sqlite3.connect(target/'learning.db')) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
        self.assertEqual(file_sha256(self.config.library_database),before)

    def test_personal_rotation_only_removes_owned_names_after_success(self):
        folder=self.data/'backups';folder.mkdir()
        unrelated=['manual.zip','mathlens-20200101-000000-abcdef.zip','mathlens-library-20200101-000000-000000000000.zip',
                   'mathlens-personal-20200101-000000-000000000000.zip']
        for name in unrelated:
            with zipfile.ZipFile(folder/name,'w') as archive:
                archive.writestr('backup-manifest.json',json.dumps(dict(format=3,producer='someone-else')))
        paths=[Path(backup(self.data,ROOT)['path']) for _ in range(5)]
        self.assertEqual({p.name for p in paths if p.exists()},{p.name for p in paths[-3:]})
        self.assertTrue(all((folder/n).is_file() for n in unrelated))
        with patch('app.storage.backup_archive.validate',side_effect=ValueError('verification failed')):
            with self.assertRaisesRegex(ValueError,'verification failed'):backup(self.data,ROOT)
        self.assertTrue(all(p.exists() for p in paths[-3:]))
        self.assertEqual(len(list(folder.glob('*.partial'))),0)

    def test_restore_accepts_newer_but_refuses_other_or_missing_library(self):
        archive=backup(self.data,ROOT)['path']
        with self.db.session(write=True,library_write=True) as conn:
            conn.execute("UPDATE bank_questions SET stem='changed' WHERE id='q'")
        result=restore(archive,self.base/'newer')
        self.assertEqual(result['library_status'],'newer');self.assertIn('比备份时新',result['library_notice'])
        other=self.base/'different-library'
        Database(AppConfig(ROOT,self.base/'other-workspace',ROOT/'dist',self.base/'other-workspace'/'learning.db',library=other)).initialize()
        with self.assertRaisesRegex(ValueError,'library_mismatch'):restore(archive,self.base/'wrong',library_dir=other)
        self.assertFalse((self.base/'wrong').exists())
        with self.assertRaisesRegex(ValueError,'library_missing'):restore(archive,self.base/'missing',library_dir=self.base/'not-present')
        self.assertFalse((self.base/'missing').exists())

    def test_library_roundtrip_and_explicit_relocation_for_personal_restore(self):
        saved=backup_library(self.library)
        self.assertEqual(Path(saved['path']).parent,self.base/'backups')
        copied=self.base/'copied-library';restore_library(saved['path'],copied)
        for path in ('bank-assets/q.png','knowledge-sources/source/index.json'):
            self.assertEqual((copied/path).read_bytes(),(self.library/path).read_bytes())
        with closing(sqlite3.connect(copied/'library.db')) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],1)
        personal=backup(self.data,ROOT)['path']
        with self.db.session(write=True,library_write=True) as conn:conn.execute("UPDATE bank_questions SET stem='later version'")
        restore(personal,self.base/'relocated',library_dir=copied)
        self.assertEqual(workspace_config(self.base/'relocated').library_dir,copied)
        with self.assertRaises(ValueError):restore_library(saved['path'],copied)

    def test_library_rotation_keeps_five_and_leaves_manual_archives(self):
        folder=self.base/'backups';folder.mkdir()
        manual=folder/'manual.zip';manual.write_bytes(b'not our archive')
        lookalike=folder/'mathlens-library-20200101-000000-000000000000.zip'
        with zipfile.ZipFile(lookalike,'w') as archive:
            archive.writestr('backup-manifest.json','[]')
        paths=[Path(backup_library(self.library)['path']) for _ in range(7)]
        self.assertEqual([p.exists() for p in paths],[False,False,True,True,True,True,True])
        self.assertTrue(manual.exists());self.assertTrue(lookalike.exists())

    def test_library_backup_rejects_active_session_and_sql_writer(self):
        with closing(sqlite3.connect(self.data/'agent-session.db')) as conn,conn:
            conn.execute('UPDATE session SET payload=?',(json.dumps(dict(active_request='active')),))
        with self.assertRaisesRegex(ValueError,'正在使用'):backup_library(self.library)
        with closing(sqlite3.connect(self.data/'agent-session.db')) as conn,conn:
            conn.execute('UPDATE session SET payload=?',(json.dumps(dict(active_request=None)),))
        with closing(sqlite3.connect(self.config.library_database)) as writer:
            writer.execute('BEGIN IMMEDIATE')
            with self.assertRaisesRegex(ValueError,'正在写入'):backup_library(self.library)
        self.assertFalse((self.base/'backups').exists())

    def test_library_backup_rejects_queued_automatic_workflow(self):
        import uuid
        from app.learning.workflows import enqueue
        with self.db.session(write=True) as conn:enqueue(conn,ROOT,self.data,'analyze_paper','p',str(uuid.uuid4()))
        with self.assertRaisesRegex(ValueError,'待执行'):backup_library(self.library)
        self.assertFalse((self.base/'backups').exists())

    def test_legacy_split_zip_restores_its_own_library(self):
        # A format-2 fixture models archives produced before B8, independently
        # of the new personal-backup writer.
        target=self.base/'legacy.zip';files={}
        with tempfile.TemporaryDirectory(dir=self.base) as temporary:
            staged=Path(temporary)
            for name,source in (('learning.db',self.config.database),('__library__/library.db',self.config.library_database)):
                actual=staged/Path(name).name
                snapshot(source,actual);files[name]=actual.read_bytes()
            files['workspace.json']=(self.data/'workspace.json').read_bytes()
            files['__library__/bank-assets/q.png']=(self.library/'bank-assets/q.png').read_bytes()
            manifest=dict(format=2,data_root=str(self.data),project_root=str(ROOT),workspace_database='learning.db',
                sha256={n:hashlib.sha256(b).hexdigest() for n,b in files.items()})
            with zipfile.ZipFile(target,'w') as archive:
                for name,raw in files.items():archive.writestr(name,raw)
                archive.writestr('backup-manifest.json',json.dumps(manifest))
        restored=self.base/'legacy-restored';restore(target,restored)
        self.assertEqual(workspace_config(restored).library_dir,restored/'__library__')
        self.assertEqual((restored/'__library__'/'bank-assets'/'q.png').read_bytes(),b'bank-assets/q.png')
        with closing(sqlite3.connect(restored/'__library__'/'library.db')) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],1)

    def test_data_status_retains_backup_time_and_advertises_three_copies(self):
        from app.storage.path_upgrade import status
        self.assertIsNone(status(self.config)['last_backup_at'])
        backup(self.data,ROOT)
        info=status(self.config)
        self.assertIsNotNone(info['last_backup_at']);self.assertEqual(info['backup_retention_count'],3)

    def test_http_backup_and_restore_report_mismatch_then_accept_explicit_matching_copy(self):
        from app.main import create_app
        from fastapi.testclient import TestClient
        app=create_app(self.config,agent_factory=None)
        with TestClient(app,base_url='http://127.0.0.1') as http:
            response=http.post('/api/maintenance/backup')
            self.assertEqual(response.status_code,200,response.text)
            name=Path(response.json()['path']).name
            self.assertEqual(response.json()['retention_count'],3)
            library_archive=backup_library(self.library)['path']
            copied=self.base/'matching-library';restore_library(library_archive,copied)
            with self.db.session(write=True,library_write=True) as conn:conn.execute("UPDATE bank_questions SET stem='later'")
            rejected=http.post('/api/maintenance/restore',json=dict(name=name))
            self.assertEqual(rejected.status_code,200,rejected.text);self.assertEqual(rejected.json()['library_status'],'newer')
            restored=http.post('/api/maintenance/restore',json=dict(name=name,library_dir=str(copied)))
            self.assertEqual(restored.status_code,200,restored.text)
            self.assertEqual(workspace_config(Path(restored.json()['restored_to'])).library_dir,copied)

    def test_corrupt_archive_never_creates_restore_directory(self):
        saved=backup(self.data,ROOT)['path'];corrupt=self.base/'corrupt.zip'
        with zipfile.ZipFile(saved) as old,zipfile.ZipFile(corrupt,'w') as new:
            for name in old.namelist():new.writestr(name,b'bad' if name=='learning.db' else old.read(name))
        with self.assertRaisesRegex(ValueError,'校验失败'):restore(corrupt,self.base/'corrupt-restore')
        self.assertFalse((self.base/'corrupt-restore').exists())

    def test_older_library_requires_real_confirmation(self):
        older=self.base/'older-library';restore_library(backup_library(self.library)['path'],older)
        with self.db.session(write=True,library_write=True) as conn:conn.execute("UPDATE bank_questions SET stem='new content'")
        personal=backup(self.data,ROOT)['path']
        for flag in (False,1,'true'):
            with self.assertRaisesRegex(ValueError,'library_older'):
                restore(personal,self.base/'not-confirmed',library_dir=older,confirm_older_library=flag)
        result=restore(personal,self.base/'confirmed',library_dir=older,confirm_older_library=True)
        self.assertEqual(result['library_status'],'older')

    def test_personal_identity_never_snapshots_library_and_survives_vacuum(self):
        from app.storage.library_identity import read
        before=read(self.library)
        def personal_only(source,target):
            self.assertNotEqual(Path(source),self.config.library_database)
            snapshot(source,target)
        with patch('app.storage.split_backup.snapshot',side_effect=personal_only):backup(self.data,ROOT)
        with closing(sqlite3.connect(self.config.library_database)) as conn:conn.execute('VACUUM')
        self.assertEqual(read(self.library),before)

    def test_explicit_library_cli_backup_restore_and_required_argument(self):
        import subprocess,sys
        script=ROOT/'scripts'/'backup_library.py'
        result=subprocess.run([sys.executable,str(script),'--library',str(self.library)],capture_output=True,text=True,encoding='utf8',cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
        saved=json.loads(result.stdout);copied=self.base/'cli-restored'
        result=subprocess.run([sys.executable,str(script),'--library',str(copied),'--restore',saved['path']],capture_output=True,text=True,encoding='utf8',cwd=ROOT)
        self.assertEqual(result.returncode,0,result.stderr)
        self.assertEqual(Path(json.loads(result.stdout)['library']['location']),copied)
        self.assertEqual((copied/'bank-assets'/'q.png').read_bytes(),b'bank-assets/q.png')
        result=subprocess.run([sys.executable,str(script)],capture_output=True,text=True,encoding='utf8',cwd=ROOT)
        self.assertEqual(result.returncode,2)

    def test_restored_marker_cannot_be_overridden_to_unverified_library(self):
        import os
        saved=backup(self.data,ROOT)['path'];target=self.base/'overridden'
        with patch.dict(os.environ,dict(MATHLENS_DATA_DIR=str(target),MATHLENS_LIBRARY_DIR=str(self.base/'wrong-library'))):
            with self.assertRaisesRegex(ValueError,'library_override_conflict'):restore(saved,target)
        self.assertFalse(target.exists())

    def test_path_upgrade_keeps_library_backup_when_it_will_modify_library(self):
        from app.storage.path_upgrade import preview,upgrade
        # Check the integration without manufacturing a hashless path change:
        # inventory correctly refuses unverified bank resource paths.
        plan=preview(self.config);plan['changes']=[dict(store='library',table='bank_resources')]
        with patch('app.storage.path_upgrade.preview',return_value=plan), \
             patch('app.storage.library_backup.backup_library',side_effect=ValueError('library backup required')) as reserve:
            with self.assertRaisesRegex(ValueError,'library backup required'):upgrade(self.config,plan['plan_sha256'])
        reserve.assert_called_once_with(self.library,workspaces=[self.data])
