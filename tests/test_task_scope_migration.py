import sqlite3
import unittest
from app.storage.task_scope_migration import migrate


class TaskScopeMigrationTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(':memory:');self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.executescript('''
          CREATE TABLE papers(id TEXT PRIMARY KEY);
          CREATE TABLE learning_tasks(id TEXT PRIMARY KEY,paper_id TEXT NOT NULL REFERENCES papers(id),status TEXT NOT NULL);
          CREATE UNIQUE INDEX active_task ON learning_tasks((1)) WHERE status='running';
          CREATE TABLE learning_results(id TEXT PRIMARY KEY,task_id TEXT REFERENCES learning_tasks(id),paper_id TEXT NOT NULL REFERENCES papers(id));
          CREATE TABLE workflow_jobs(id TEXT PRIMARY KEY,paper_id TEXT NOT NULL REFERENCES papers(id),task_id TEXT REFERENCES learning_tasks(id));
          CREATE TABLE result_references(result_id TEXT REFERENCES learning_results(id));
          INSERT INTO papers VALUES('paper-real');
          INSERT INTO learning_tasks(rowid,id,paper_id,status) VALUES(7,'task-real','paper-real','completed');
          INSERT INTO learning_results VALUES('result-real','task-real','paper-real');
          INSERT INTO workflow_jobs VALUES('job-real','paper-real','task-real');
          INSERT INTO result_references VALUES('result-real');
        ''')

    def tearDown(self):self.conn.close()

    def test_keeps_rows_rowids_indexes_and_foreign_keys_then_allows_nonpaper_scope(self):
        before = {name: [tuple(r) for r in self.conn.execute('SELECT rowid,* FROM '+name)]
                  for name in ('learning_tasks','learning_results','workflow_jobs','result_references')}
        result = migrate(self.conn)
        self.assertEqual(len(result['changed_tables']), 3)
        for name, rows in before.items():self.assertEqual(rows, [tuple(r) for r in self.conn.execute('SELECT rowid,* FROM '+name)])
        self.assertEqual(self.conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(list(self.conn.execute('PRAGMA foreign_key_check')), [])
        self.conn.execute("INSERT INTO learning_tasks VALUES('bank-task',NULL,'running')")
        with self.assertRaises(sqlite3.IntegrityError):self.conn.execute("INSERT INTO learning_tasks VALUES('other-task',NULL,'running')")
        self.conn.execute("INSERT INTO learning_results VALUES('bank-result','bank-task',NULL)")
        self.conn.execute("INSERT INTO workflow_jobs VALUES('bank-job',NULL,'bank-task')")
        self.conn.commit()
        self.assertEqual(migrate(self.conn), {'changed_tables': []})

    def test_startup_migration_does_not_commit_an_existing_caller_transaction(self):
        self.conn.execute("INSERT INTO papers VALUES('uncommitted')")
        with self.assertRaisesRegex(ValueError, '独立事务'):migrate(self.conn)
        self.assertTrue(self.conn.in_transaction)
        self.conn.rollback()
        self.assertFalse(self.conn.execute("SELECT 1 FROM papers WHERE id='uncommitted'").fetchone())

    def test_failure_after_first_table_rolls_back_entire_schema(self):
        self.conn.execute('ALTER TABLE learning_results RENAME COLUMN paper_id TO other_paper')
        # This incompatible declaration is detected after tasks were rebuilt.
        self.conn.execute('ALTER TABLE learning_results ADD COLUMN paper_id VARCHAR NOT NULL DEFAULT "paper-real"')
        before = [tuple(r) for r in self.conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")]
        with self.assertRaisesRegex(ValueError, '已知迁移'):migrate(self.conn)
        self.assertEqual(before, [tuple(r) for r in self.conn.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name")])
        self.assertEqual(self.conn.execute('PRAGMA foreign_keys').fetchone()[0], 1)
        self.assertEqual(list(self.conn.execute('PRAGMA foreign_key_check')), [])

    def test_unrelated_legacy_orphans_are_preserved_and_not_silently_deleted(self):
        self.conn.execute('CREATE TABLE questions(id TEXT PRIMARY KEY,paper_id TEXT REFERENCES papers(id))')
        self.conn.commit();self.conn.execute('PRAGMA foreign_keys=OFF')
        self.conn.execute("INSERT INTO questions VALUES('historical-orphan','missing-paper')");self.conn.commit()
        self.conn.execute('PRAGMA foreign_keys=ON')
        before={tuple(r) for r in self.conn.execute('PRAGMA foreign_key_check')}
        result=migrate(self.conn)
        self.assertEqual(result['preserved_legacy_reference_issues'],1)
        self.assertEqual({tuple(r) for r in self.conn.execute('PRAGMA foreign_key_check')},before)
        self.assertEqual(self.conn.execute('SELECT id FROM questions').fetchone()[0],'historical-orphan')
