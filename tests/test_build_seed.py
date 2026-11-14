from contextlib import closing
import hashlib, json, sqlite3, tempfile, unittest
from pathlib import Path
from app.config import AppConfig
from app.storage.database import Database
from scripts.packaging.build_seed import build
from app.desktop.prepare import manifest, validate_database

class BuildSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup); self.root=Path(self.temp.name); self.library=self.root/'source'; self.library.mkdir()
        config=AppConfig(self.root,self.root/'workspace',self.root/'dist',self.root/'workspace/learning.db',library=self.library); Database(config).initialize()
        (self.library/'bank-assets').mkdir(); (self.library/'knowledge-sources/v1').mkdir(parents=True)
        (self.library/'bank-assets/used.png').write_bytes(b'used'); (self.library/'bank-assets/unused.png').write_bytes(b'unused'); (self.library/'knowledge-sources/v1/definition.md').write_text('definition',encoding='utf8')
        with Database(config).session(write=True,library_write=True) as conn:
            conn.execute("INSERT INTO bank_questions(id,source,stem,answer,created_at) VALUES('q1','fixture','text','2','now')")
            conn.execute("INSERT INTO bank_resources VALUES('q1',?, 'bank-assets/used.png',NULL,NULL)",(json.dumps({'resources':{'question':{'images':[{'path':'bank-assets/used.png'}]}}}),))
            conn.execute("INSERT INTO knowledge_source_versions VALUES('v1','fixture','1','sha',?)",(json.dumps({}),))
            conn.execute("INSERT INTO knowledge_source_entries VALUES('v1','e1','definition','sha',?)",(json.dumps({'references':[{'path':'definition.md','sha256':hashlib.sha256(b'definition').hexdigest()}]}),))
        self.before=(self.library/'library.db').read_bytes()

    def test_referenced_seed_hashes_validates_and_reports_unused_without_source_write(self):
        output=self.root/'library-seed'; report=build(self.library,output,'fixture-release')
        self.assertTrue(report['output_published']); self.assertEqual(report['unreferenced_file_count'],1); self.assertEqual(report['unreferenced_bytes'],len(b'unused'))
        self.assertEqual((self.library/'library.db').read_bytes(),self.before)
        files={p.relative_to(output).as_posix() for p in output.rglob('*') if p.is_file()}
        self.assertEqual(files,{'library.db','manifest.json','bank-assets/used.png','knowledge-sources/v1/definition.md'})
        value=manifest(output); validate_database(output,value)
        self.assertEqual(value['release_id'],'fixture-release'); self.assertEqual(value['counts'],{'questions':1,'ready':0})
        self.assertEqual(value['files']['library.db']['sha256'],hashlib.sha256((output/'library.db').read_bytes()).hexdigest())

    def test_unlisted_table_and_wal_are_reported_and_never_deleted(self):
        with closing(sqlite3.connect(self.library/'library.db')) as conn, conn: conn.execute('CREATE TABLE maintenance_log(value TEXT)')
        with self.assertRaisesRegex(ValueError,'未列入发行白名单'): build(self.library,self.root/'bad','bad-release')
        report=json.loads((self.root/'bad.report.json').read_text(encoding='utf8')); self.assertIn('maintenance_log',report['unlisted_tables']); self.assertTrue((self.library/'library.db').is_file())
        wal=self.library/'library.db-wal'; wal.write_bytes(b'wal')
        with self.assertRaisesRegex(ValueError,'sidecar'): build(self.library,self.root/'bad2','bad-release')
        self.assertFalse((self.root/'bad2').exists())

    def test_missing_reference_fails_before_output_and_source_unchanged(self):
        config=AppConfig(self.root,self.root/'workspace',self.root/'dist',self.root/'workspace/learning.db',library=self.library)
        with Database(config).session(write=True,library_write=True) as conn: conn.execute("UPDATE bank_resources SET question_path='bank-assets/missing.png' WHERE bank_id='q1'")
        with self.assertRaisesRegex(ValueError,'缺失或越界'): build(self.library,self.root/'missing','missing-release')
        self.assertFalse((self.root/'missing').exists())
