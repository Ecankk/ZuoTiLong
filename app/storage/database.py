"""SQLite connections, schema migration and transaction scope."""
from contextlib import closing,contextmanager
import sqlite3
from app.storage.demo import seed
from app.learning.loop import init_loop

class Database:
    def __init__(self,config):self.config=config
    def connect(self, *, library_write=False, readonly=False):
        from app.storage.boundaries import connect_workspace
        return connect_workspace(self.config, library_write=library_write, readonly=readonly)
    def initialize(self):initialize(self)
    @contextmanager
    def session(self,*,write=False,library_write=False):
        with closing(self.connect(library_write=library_write)) as conn:
            if write:
                with conn:yield conn
            else:yield conn

def initialize(database) -> None:
    from app.storage.split import initialize_split
    initialize_split(database.config)


def _initialize_connection(database,conn):
    from app.storage.task_scope_migration import migrate
    migrate(conn)
    from app.storage.annotation_cache_migration import migrate as migrate_annotation_origins
    migrate_annotation_origins(conn)
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS papers (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            exam_date TEXT,
            score REAL DEFAULT 0,
            total_score REAL DEFAULT 150,
            duration INTEGER,
            source_name TEXT,
            source_path TEXT,
            import_status TEXT DEFAULT 'needs_review',
            created_at TEXT NOT NULL,
            updated_at TEXT,
            archived_at TEXT
        );
        CREATE TABLE IF NOT EXISTS questions (
            id TEXT PRIMARY KEY,
            paper_id TEXT NOT NULL REFERENCES papers(id) ON DELETE CASCADE,
            number TEXT NOT NULL,
            subject TEXT DEFAULT '数学一',
            stem TEXT,
            score_earned REAL DEFAULT 0,
            max_score REAL DEFAULT 0,
            correctness TEXT DEFAULT 'unknown',
            review_status TEXT DEFAULT '待诊断',
            error_stage TEXT,
            error_type TEXT,
            knowledge TEXT,
            fingerprint_json TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bank_questions (
            id TEXT PRIMARY KEY,
            source TEXT NOT NULL,
            source_ref TEXT,
            stem TEXT NOT NULL,
            answer TEXT,
            explanation TEXT,
            tags_json TEXT,
            fingerprint_json TEXT,
            difficulty INTEGER DEFAULT 3,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS reviews (
            id TEXT PRIMARY KEY,
            question_id TEXT NOT NULL REFERENCES questions(id) ON DELETE CASCADE,
            bank_question_id TEXT REFERENCES bank_questions(id) ON DELETE SET NULL,
            mode TEXT DEFAULT '检验',
            correct INTEGER DEFAULT 0,
            score REAL DEFAULT 0,
            elapsed INTEGER,
            confidence INTEGER,
            error_stage TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_questions_paper ON questions(paper_id);
        CREATE INDEX IF NOT EXISTS idx_questions_status ON questions(review_status);
        CREATE INDEX IF NOT EXISTS idx_bank_source ON bank_questions(source);
        """
    )
    # Keep the first version's SQLite database usable while adding source
    # evidence incrementally. SQLite has no IF NOT EXISTS for columns.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(papers)")}
    for name, definition in {
        "page_count": "INTEGER DEFAULT 0",
        "analysis_engine": "TEXT",
        "analysis_message": "TEXT",
        "analyzed_at": "TEXT",
        "updated_at": "TEXT",
        "archived_at": "TEXT",
        "score_confirmed_at": "TEXT",
        "math_type": "INTEGER",
    }.items():
        if name not in columns:
            conn.execute(f"ALTER TABLE papers ADD COLUMN {name} {definition}")
    # Existing databases predate lifecycle timestamps. Keep the original
    # creation time as the initial update time and leave archived_at empty.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(papers)")}
    if "updated_at" in columns:
        conn.execute("UPDATE papers SET updated_at=created_at WHERE updated_at IS NULL")
    question_columns = {row["name"] for row in conn.execute("PRAGMA table_info(questions)")}
    for name, definition in {
        "page_start": "INTEGER",
        "page_end": "INTEGER",
        "bbox_json": "TEXT",
        "ocr_confidence": "REAL",
        "match_bank_id": "TEXT",
        "match_score": "REAL",
        "source_text": "TEXT",
    }.items():
        if name not in question_columns:
            conn.execute(f"ALTER TABLE questions ADD COLUMN {name} {definition}")
    init_loop(conn)
    from app.bank.identity_reviews import initialize as initialize_identity_reviews
    initialize_identity_reviews(conn)
    from app.learning.tasks import init_tasks
    init_tasks(conn)
    from app.learning.dates import initialize as dates
    dates(conn)
    from app.learning.feedback import initialize as initialize_feedback
    initialize_feedback(conn)
    from app.bank.metadata import initialize as initialize_bank_metadata
    initialize_bank_metadata(conn)
    from app.bank.source_records import initialize as initialize_bank_sources
    initialize_bank_sources(conn)
    from app.bank.collections import initialize as initialize_collections
    initialize_collections(conn)
    from app.bank.applicability import initialize as applicability
    applicability(conn)
    from app.storage.navigation_index import initialize as initialize_navigation
    initialize_navigation(conn)
    if database.config.demo and conn.execute("SELECT COUNT(*) FROM papers").fetchone()[0] == 0:
        seed(conn)
    from app.bank.entities import initialize as initialize_entities
    initialize_entities(conn)
    conn.commit()
