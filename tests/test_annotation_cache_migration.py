import sqlite3
import unittest
from app.storage.annotation_cache_migration import migrate


class AnnotationOriginMigrationTests(unittest.TestCase):
    def setUp(self):
        self.conn=sqlite3.connect(':memory:');self.conn.row_factory=sqlite3.Row
        self.addCleanup(self.conn.close)
        self.conn.executescript('''
            PRAGMA foreign_keys=ON;
            CREATE TABLE learning_results(id TEXT PRIMARY KEY);
            CREATE TABLE diagnostic_probes(id TEXT PRIMARY KEY);
            CREATE TABLE bank_questions(id TEXT PRIMARY KEY);
            CREATE TABLE question_annotations(id TEXT PRIMARY KEY);
            CREATE TABLE practice_question_bindings(
                result_id TEXT REFERENCES learning_results(id),probe_id TEXT REFERENCES diagnostic_probes(id),
                bank_id TEXT REFERENCES bank_questions(id),annotation_id TEXT REFERENCES question_annotations(id),
                content_revision TEXT,material_revision TEXT,payload_json TEXT,PRIMARY KEY(result_id,probe_id));
            CREATE TABLE practice_attempt_materials(attempt_id TEXT PRIMARY KEY,binding_result_id TEXT,probe_id TEXT,
                FOREIGN KEY(binding_result_id,probe_id) REFERENCES practice_question_bindings(result_id,probe_id));
            INSERT INTO learning_results VALUES('result');INSERT INTO diagnostic_probes VALUES('probe');
            INSERT INTO bank_questions VALUES('bank');INSERT INTO question_annotations VALUES('annotation');
            INSERT INTO practice_question_bindings(rowid,result_id,probe_id,bank_id,annotation_id,content_revision,material_revision,payload_json)
                VALUES(27,'result','probe','bank','annotation','content','material','{"version":"unchanged"}');
            INSERT INTO practice_attempt_materials VALUES('attempt','result','probe');
            CREATE INDEX idx_legacy_binding_material ON practice_question_bindings(material_revision);
            CREATE TRIGGER legacy_binding_trigger AFTER INSERT ON practice_question_bindings BEGIN SELECT 1; END;
        ''')

    def rows(self):
        return [tuple(r) for r in self.conn.execute('SELECT rowid,* FROM practice_question_bindings')]

    def test_preserves_binding_rows_referencing_attempts_indexes_and_triggers(self):
        before=self.rows();attempts=list(map(tuple,self.conn.execute('SELECT * FROM practice_attempt_materials')))
        original_sources=list(map(tuple,self.conn.execute('SELECT * FROM question_annotations')))
        self.assertEqual(migrate(self.conn)['changed_tables'],['practice_question_bindings'])
        self.assertEqual(self.rows(),before)
        self.assertEqual(list(map(tuple,self.conn.execute('SELECT * FROM practice_attempt_materials'))),attempts)
        self.assertEqual(list(map(tuple,self.conn.execute('SELECT * FROM question_annotations'))),original_sources)
        self.assertIn('prepared_annotation_ids',{r[2] for r in self.conn.execute('PRAGMA foreign_key_list(practice_question_bindings)')})
        self.assertEqual(self.conn.execute('SELECT id FROM prepared_annotation_ids').fetchone()[0],'annotation')
        self.assertEqual(list(self.conn.execute('PRAGMA foreign_key_check')),[])
        for name in ('idx_legacy_binding_material','legacy_binding_trigger'):
            self.assertIsNotNone(self.conn.execute('SELECT 1 FROM sqlite_master WHERE name=?',(name,)).fetchone())
        self.assertEqual(migrate(self.conn)['changed_tables'],[])

    def test_rollback_after_copy_and_drop_restores_original_table_and_connection_flags(self):
        actual=self.conn;before=self.rows()
        class Fault:
            def __getattr__(self,name):return getattr(actual,name)
            def execute(self,sql,*args):
                if sql.startswith('ALTER TABLE _annotation_origin_bindings'):
                    raise RuntimeError('injected rename failure')
                return actual.execute(sql,*args)
        with self.assertRaisesRegex(RuntimeError,'injected'):migrate(Fault())
        self.assertEqual(self.rows(),before)
        self.assertEqual(actual.execute('PRAGMA foreign_keys').fetchone()[0],1)
        self.assertIn('question_annotations',{r[2] for r in actual.execute('PRAGMA foreign_key_list(practice_question_bindings)')})
        self.assertIsNone(actual.execute("SELECT 1 FROM sqlite_master WHERE name='_annotation_origin_bindings'").fetchone())

    def test_unrelated_old_foreign_key_problem_is_preserved_not_deleted_or_guessed(self):
        self.conn.executescript("PRAGMA foreign_keys=OFF;CREATE TABLE papers(id TEXT PRIMARY KEY);CREATE TABLE questions(id TEXT PRIMARY KEY,paper_id TEXT REFERENCES papers(id));INSERT INTO questions VALUES('old-orphan','unknown');PRAGMA foreign_keys=ON;")
        issues={tuple(r) for r in self.conn.execute('PRAGMA foreign_key_check')}
        self.assertEqual(migrate(self.conn)['preserved_reference_issues'],1)
        self.assertEqual({tuple(r) for r in self.conn.execute('PRAGMA foreign_key_check')},issues)
        self.assertEqual(self.conn.execute('SELECT paper_id FROM questions').fetchone()[0],'unknown')

    def test_no_migration_inside_an_existing_transaction(self):
        self.conn.execute('BEGIN')
        with self.assertRaisesRegex(ValueError,'独立事务'):migrate(self.conn)
        self.conn.rollback()


if __name__=='__main__':unittest.main()
