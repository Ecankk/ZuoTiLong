"""Isolated-path helpers for existing tests; this module is not a service entry point."""
from app.config import AppConfig
from app.storage.database import Database
from app.services.papers import PaperService, set_paper_archive, confirm_paper_score
from app.services.practice import queue_attempt_grading as _queue_attempt_grading
from app.common import now_iso

_config = AppConfig.from_env()
ROOT, DATA, DIST = _config.root, _config.data, _config.dist
DB_PATH, PAPERS_DIR = _config.database, _config.papers


def config():
    return AppConfig(ROOT, DATA, DIST, DB_PATH)


def connect():
    return Database(config()).connect(library_write=True)


def init_db():
    Database(config()).initialize()


def analyze_paper_record(conn, paper_id):
    return PaperService(config(), Database(config())).analyze(conn, paper_id)


def queue_attempt_grading(conn, attempt_id):
    return _queue_attempt_grading(conn, attempt_id, ROOT, DATA)
