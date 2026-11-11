from contextlib import closing
import sqlite3,tempfile,unittest
from pathlib import Path
from fastapi.testclient import TestClient
from app.config import AppConfig
from app.main import create_app
from app.storage.database import Database


class ExistingDatabaseUpgradeTests(unittest.TestCase):
    def test_partial_upgrade_normalizes_nullable_columns(self):
        from app.learning.dates import initialize
        with closing(sqlite3.connect(':memory:')) as conn:
            conn.execute('CREATE TABLE papers(exam_date TEXT,exam_date_precision TEXT,exam_date_unknown_reason TEXT,import_decision TEXT)')
            conn.executemany('INSERT INTO papers VALUES(?,?,?,?)',[('',None,None,None),('2025-01','','','')])
            initialize(conn)
            self.assertEqual(list(conn.execute('SELECT * FROM papers')),[(None,'unknown','not_provided','accepted'),('2025-01','month','','accepted')])

    def test_source_projection_builds_plan_once_per_paper_without_changing_output(self):
        import test_learning_loop as fixtures
        from unittest.mock import patch
        from app.knowledge.index import sources
        from app.learning.plans import practice_state
        f=fixtures.LearningLoopTests();f.setUp();self.addCleanup(f.tearDown);f.apply()
        f.conn.execute('''INSERT INTO diagnostic_probes SELECT id||'-fragment',paper_id,question_id,bank_id,
            skill_id,payload_json,status,created_at FROM diagnostic_probes LIMIT 1''');f.conn.commit()
        before=sources(f.conn)
        with patch('app.learning.plans.practice_state',wraps=practice_state) as state:
            after=sources(f.conn)
        self.assertEqual(after,before)
        self.assertEqual(state.call_count,1)

    def test_raw_old_schema_upgrades_and_existing_papers_remain_readable(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);data=root/'workspace';data.mkdir()
            config=AppConfig(root,data,root/'dist',data/'learning.db',library=root/'library')
            # Deliberately create an old on-disk schema directly, not the new template.
            with closing(sqlite3.connect(config.database)) as conn,conn:
                conn.execute('''CREATE TABLE papers(id TEXT PRIMARY KEY,title TEXT NOT NULL,exam_date TEXT,
                    score REAL DEFAULT 0,total_score REAL DEFAULT 150,duration INTEGER,source_name TEXT,
                    source_path TEXT,import_status TEXT DEFAULT 'needs_review',created_at TEXT NOT NULL,
                    updated_at TEXT,archived_at TEXT,page_count INTEGER,analysis_engine TEXT,analysis_message TEXT,
                    analyzed_at TEXT,score_confirmed_at TEXT,math_type INTEGER,source_sha256 TEXT)''')
                conn.executemany('INSERT INTO papers(id,title,exam_date,created_at) VALUES(?,?,?,?)',
                    [('old-day','2021数学一','2025-01-02','2025-01-03'),('old-month','2022数学二','2025-02','2025-03-01'),('old-empty','history','','2025-01-01')])
            with TestClient(create_app(config,agent_factory=None),base_url='http://127.0.0.1') as http:
                for url in ('/api/papers','/api/papers?limit=20','/api/papers/old-day','/api/profile/overview'):
                    value=http.get(url);self.assertEqual(value.status_code,200,(url,value.text))
                import pymupdf
                with pymupdf.open() as pdf:
                    pdf.new_page().insert_text((30,30),'1. Test question');content=pdf.tobytes()
                response=http.post('/api/papers/import',files={'file':('test.pdf',content,'application/pdf')})
                self.assertEqual(response.status_code,201,response.text)
                pid=response.json()['paper']['id']
                self.assertEqual(http.get('/api/papers/'+pid).status_code,200)
                with closing(sqlite3.connect(config.database)) as conn:
                    before=list(conn.execute('SELECT id,exam_date,exam_date_precision,exam_date_unknown_reason,import_decision FROM papers ORDER BY id'))
                    tables={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                    self.assertTrue({'profile_practice_batches','profile_practice_exercises','profile_practice_attempts','feedback_read_receipts'}<=tables)
                    self.assertIn(('old-empty',None,'unknown','not_provided','accepted'),before)
                    self.assertIn(('old-month','2025-02','month',None,'accepted'),before)
                Database(config).initialize()
                with closing(sqlite3.connect(config.database)) as conn:
                    self.assertEqual(list(conn.execute('SELECT id,exam_date,exam_date_precision,exam_date_unknown_reason,import_decision FROM papers ORDER BY id')),before)
