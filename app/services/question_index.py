"""Portable index operations, with short source-DB read locks."""
from contextlib import contextmanager
import sqlite3
from app.bank import annotation_packages
from app.storage import annotation_cache


class QuestionIndexService:
    def __init__(self, config, database):
        self.config, self.database = config, database

    @contextmanager
    def snapshot(self):
        from app.storage.knowledge_reads import navigation_snapshot
        with navigation_snapshot(self.database) as conn:
            yield conn

    def listing(self):
        with self.database.session() as conn:
            return {'packages': annotation_cache.listing(conn)}

    def export(self):
        with self.snapshot() as conn:
            return annotation_packages.export_package(conn, self.config.data)

    def preview(self, package):
        with self.snapshot() as conn:
            return annotation_packages.preview(conn, self.config.data, package)

    def import_package(self, body):
        with self.database.session(write=True,library_write=True) as conn:
            return annotation_packages.import_package(conn, self.config.data, body['package'],
                trusted_sha256=body['trusted_sha256'], expected_preview_sha256=body['expected_preview_sha256'],
                confirmed=body['confirmed'])

    def set_enabled(self, body):
        with self.database.session(write=True,library_write=True) as conn:
            return annotation_packages.set_enabled(conn, body['sha256'], body['enabled'], confirmed=body['confirmed'])
