from app.storage.boundaries import library_root
from contextlib import closing
from pathlib import Path
import sqlite3
from tempfile import TemporaryDirectory
import unittest
import os
from unittest.mock import patch

from fastapi.testclient import TestClient
from app.config import AppConfig
from app.main import create_app
from app.storage.database import Database, _initialize_connection
from app.storage.boundaries import LIBRARY_TABLES
from app.storage.split import migrate_legacy

ROOT = Path(__file__).resolve().parents[1]


class StorageSeparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory(dir=ROOT/'tmp')
        self.base = Path(self.temp.name)
        self.a = self.config('a')
        self.b = self.config('b')

    def tearDown(self):self.temp.cleanup()

    def config(self,name):
        data=self.base/name
        return AppConfig(ROOT,data,ROOT/'dist',data/'learning.db',library=self.base/'library')

    def names(self,path):
        with closing(sqlite3.connect(path)) as conn:
            return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}

    def test_physical_tables_and_default_learning_connection_cannot_write_library(self):
        db=Database(self.a);db.initialize()
        self.assertEqual(self.names(self.a.library_database),LIBRARY_TABLES)
        self.assertFalse(self.names(self.a.database)&LIBRARY_TABLES)
        with db.session(write=True) as conn:
            with self.assertRaises(sqlite3.OperationalError):
                conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('no','x','x','now')")
        with db.session(write=True,library_write=True) as conn:
            conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('shared','x','x','now')")
        with db.session() as conn:self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],1)

    def test_two_workspaces_share_library_but_not_history_or_exposure(self):
        Database(self.a).initialize();Database(self.b).initialize()
        with Database(self.a).session(write=True,library_write=True) as conn:
            conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('shared','x','x','now')")
            conn.execute("INSERT INTO bank_views VALUES('shared','question','now')")
            conn.execute("INSERT INTO papers(id,title,created_at) VALUES('personal','only A','now')")
        with Database(self.b).session() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],1)
            for table in ('papers','probe_attempts','learning_events','bank_views','learning_tasks'):
                self.assertEqual(conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_library_override_selects_the_same_database_and_materials(self):
        from app.services.library import LibraryService
        from app.storage.boundaries import workspace_config, material_path
        other=AppConfig(ROOT,self.b.data,ROOT/'dist',self.b.database,library=self.base/'override')
        for config,identity in ((self.a,'stored'),(other,'override')):
            db=Database(config);db.initialize()
            LibraryService(config,db).import_text({'questions':[{'id':identity,'stem':identity}]})
            for relative in ('bank-assets/shared.png','knowledge-sources/source/original.pdf'):
                path=config.library_dir/relative
                path.parent.mkdir(parents=True,exist_ok=True)
                path.write_bytes(identity.encode())
        # Keep the stale workspace marker: resolution must not depend on startup
        # rewriting it before a resource/Agent reader gets called.
        marker=(self.a.data/'workspace.json').read_bytes()
        with patch.dict(os.environ,{'MATHLENS_DATA_DIR':str(self.a.data),
                                    'MATHLENS_LIBRARY_DIR':str(other.library_dir)}):
            config=AppConfig.from_env(ROOT)
            scoped=workspace_config(self.a.data,ROOT)
            self.assertEqual(config.library_database,scoped.library_database)
            self.assertEqual(library_root(self.a.data),config.library_dir)
            with Database(scoped).session() as conn:
                self.assertEqual([r[0] for r in conn.execute('SELECT id FROM bank_questions')],['override'])
            for relative in ('bank-assets/shared.png','knowledge-sources/source/original.pdf'):
                self.assertEqual(material_path(self.a.data,relative).read_bytes(),b'override')
            self.assertEqual(material_path(self.a.data,'papers/original.pdf'),self.a.data/'papers/original.pdf')
        self.assertEqual((self.a.data/'workspace.json').read_bytes(),marker)
        with patch.dict(os.environ):
            os.environ.pop('MATHLENS_LIBRARY_DIR',None)
            self.assertEqual(workspace_config(self.a.data).library_dir,self.a.library_dir)
            self.assertEqual(library_root(self.a.data),self.a.library_dir)

    def test_library_override_also_applies_without_a_workspace_marker(self):
        from app.storage.boundaries import workspace_config, material_path
        with patch.dict(os.environ,{'MATHLENS_DATA_DIR':str(self.a.data),
                                    'MATHLENS_LIBRARY_DIR':str(self.base/'override')}):
            config=AppConfig.from_env(ROOT)
            self.assertEqual(workspace_config(self.a.data).library_dir,config.library_dir)
            self.assertEqual(material_path(self.a.data,'bank-assets/q.png'),config.library_dir/'bank-assets/q.png')

    def test_library_override_does_not_follow_other_workspaces_or_restores(self):
        from app.services.library import LibraryService
        from app.storage.boundaries import workspace_config, material_path
        from app.storage.maintenance import backup, restore
        selected=self.base/'selected';selected.mkdir()
        decoy=self.base/'decoy';decoy.mkdir()
        with patch.dict(os.environ,{'MATHLENS_DATA_DIR':str(selected),
                                    'MATHLENS_LIBRARY_DIR':str(decoy)}):
            # A marked workspace keeps its recorded library, even though this
            # process was launched for a different workspace.
            Database(self.a).initialize()
            scoped=workspace_config(self.a.data)
            self.assertEqual(scoped.library_dir,self.a.library_dir)
            self.assertEqual(library_root(self.a.data),self.a.library_dir)
            LibraryService(scoped,Database(scoped)).import_text({'questions':[{'id':'local','stem':'local'}]})
            path=material_path(self.a.data,'bank-assets/local.png')
            path.parent.mkdir(parents=True);path.write_bytes(b'local')
            archive=backup(self.a.data,ROOT)['path']
            target=self.base/'restored'
            restore(archive,target)
            restored=workspace_config(target)
            self.assertNotEqual(restored.library_dir,scoped.library_dir)
            self.assertEqual(library_root(target),restored.library_dir)
            self.assertEqual(material_path(target,'bank-assets/local.png').read_bytes(),b'local')
            with Database(restored).session() as conn:
                self.assertEqual(conn.execute('SELECT id FROM bank_questions').fetchone()[0],'local')
            # Unmarked/new directories must not pick up the other workspace's
            # override either; legacy material fallback remains local.
            self.assertEqual(workspace_config(self.b.data).library_dir,self.b.data/'library')
            self.assertEqual(library_root(self.b.data),self.b.data)
            self.assertEqual(list(selected.iterdir()),[])
            self.assertEqual(list(decoy.iterdir()),[])

    def test_library_override_requires_an_explicit_matching_data_directory(self):
        from app.storage.boundaries import workspace_config
        Database(self.a).initialize()
        with patch.dict(os.environ,{'MATHLENS_LIBRARY_DIR':str(self.base/'decoy')}):
            os.environ.pop('MATHLENS_DATA_DIR',None)
            self.assertEqual(workspace_config(self.a.data).library_dir,self.a.library_dir)
            self.assertEqual(library_root(self.a.data),self.a.library_dir)
        with patch.dict(os.environ,{'MATHLENS_DATA_DIR':str(self.a.data/'..'/'a'),
                                    'MATHLENS_LIBRARY_DIR':str(self.base/'override')}):
            self.assertEqual(workspace_config(self.a.data).library_dir,self.base/'override')
            self.assertEqual(library_root(self.a.data),self.base/'override')

    def test_http_import_and_reveal_do_not_create_private_library_tables(self):
        with TestClient(create_app(self.a,agent_factory=None),base_url='http://127.0.0.1') as http:
            response=http.post('/api/bank/import',json={'questions':[{'id':'shared','stem':'a question','answer':'1'}]})
            self.assertEqual(response.status_code,201,response.text)
            self.assertEqual(http.post('/api/papers',json={'title':'private'}).status_code,201)
            self.assertEqual(http.get('/api/bootstrap').status_code,200)
        with TestClient(create_app(self.b,agent_factory=None),base_url='http://127.0.0.1') as http:
            self.assertEqual(http.get('/api/papers').json()['papers'],[])
            self.assertEqual(len(http.get('/api/bank').json()['bank']),1)
        self.assertFalse({'papers','learning_tasks','preferences','bank_views'}&self.names(self.a.library_database))
        self.assertFalse(LIBRARY_TABLES&self.names(self.a.database))

    def test_legacy_migration_copies_resources_and_keeps_original(self):
        old=self.base/'legacy';old.mkdir()
        config=AppConfig(ROOT,old,ROOT/'dist',old/'mathlens.db')
        with closing(sqlite3.connect(config.database)) as conn:
            conn.row_factory=sqlite3.Row
            _initialize_connection(Database(config),conn)
            conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('shared','x','x','now')")
            conn.execute('INSERT INTO papers(id,title,source_path,created_at) VALUES(?,?,?,?)',
                         ('personal','private',str(old/'papers'/'original.pdf'),'now'))
            conn.commit()
        (old/'papers').mkdir();(old/'papers'/'original.pdf').write_bytes(b'%PDF-test')
        (old/'bank-assets').mkdir();(old/'bank-assets'/'question.png').write_bytes(b'shared-image')
        migrate_legacy(old,self.a)
        self.assertTrue(config.database.exists())
        self.assertTrue((self.a.library_dir/'bank-assets'/'question.png').exists())
        self.assertFalse((self.a.data/'bank-assets').exists())
        self.assertFalse((self.a.library_dir/'papers').exists())
        with Database(self.a).session() as conn:
            row=conn.execute('SELECT source_path FROM papers').fetchone()
            self.assertFalse(Path(row[0]).is_absolute())
            self.assertEqual((self.a.data/row[0]).read_bytes(),b'%PDF-test')
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],1)
        Database(self.b).initialize()
        with Database(self.b).session() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM papers').fetchone()[0],0)

    def test_initializer_rejects_mixed_store_instead_of_silently_using_it(self):
        self.a.data.mkdir()
        with closing(sqlite3.connect(self.a.database)) as conn:
            conn.execute('CREATE TABLE bank_questions(id TEXT)')
        with self.assertRaisesRegex(ValueError,'Mixed database'):
            Database(self.a).initialize()

    def test_backup_restores_both_files_without_reusing_original_library(self):
        from app.storage.maintenance import backup,restore
        from app.storage.boundaries import workspace_config
        db=Database(self.a);db.initialize()
        with db.session(write=True,library_write=True) as conn:
            conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('shared','x','x','now')")
            conn.execute("INSERT INTO papers(id,title,created_at) VALUES('private','private','now')")
        archive=backup(self.a.data,ROOT)['path']
        target=self.base/'restored'
        restore(archive,target)
        config=workspace_config(target,ROOT)
        self.assertNotEqual(config.library_dir,self.a.library_dir)
        with Database(config).session() as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0],1)
            self.assertEqual(conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
        self.assertFalse(self.names(config.database)&LIBRARY_TABLES)

    def test_prepared_annotation_is_usable_without_original_learning_session(self):
        from test_question_annotations import QuestionPreparationTests
        from app.bank import annotations,annotation_packages
        fixture=QuestionPreparationTests();fixture.setUp()
        try:
            ids=fixture.save_annotation()
            fresh=AppConfig(ROOT,self.b.data,ROOT/'dist',self.b.database,library=fixture.f.config.library_dir)
            Database(fresh).initialize()
            with Database(fresh).session() as conn:
                current=annotations.current(conn,fresh.data,ids[0])
                self.assertEqual(current['analysis']['status'],'ready')
                self.assertEqual(conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],0)
                package=annotation_packages.export_package(conn,fresh.data)
                self.assertTrue(package['entries'])
            with closing(sqlite3.connect(fresh.library_database)) as lib:
                self.assertNotIn('learning_results',self.names(fresh.library_database))
                proof=lib.execute('SELECT payload_json FROM annotation_provenance').fetchone()[0]
                self.assertNotIn('same-session',proof)
                self.assertNotIn('session_id',proof)
        finally:fixture.tearDown()


if __name__=='__main__':unittest.main()
