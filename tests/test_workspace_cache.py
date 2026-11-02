from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from app.config import AppConfig
from app.services.library import LibraryService
from app.services.papers import PaperService
from app.services.workspace import WorkspaceService
from app.storage.database import Database


class WorkspaceCacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.config = AppConfig(self.root, self.root, self.root/'dist', self.root/'learning.db')
        self.db = Database(self.config)
        self.db.initialize()
        self.service = WorkspaceService(self.config, self.db)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.service.close)

    def test_reuses_read_model_and_does_not_share_mutable_results(self):
        expected = self.service._build_bootstrap()
        with patch.object(self.service, '_build_bootstrap', wraps=self.service._build_bootstrap) as build:
            first = self.service.bootstrap()
            first['profile']['stages'].clear()
            with ThreadPoolExecutor(max_workers=2) as pool:
                values = list(pool.map(lambda _: self.service.bootstrap(), range(2)))
            self.assertEqual(values, [expected, expected])
            self.assertEqual(build.call_count, 1)

    def test_personal_writes_refresh_papers_preferences_and_full_read_model(self):
        self.service.bootstrap()
        PaperService(self.config, self.db).create({'title': 'new paper'})
        LibraryService(self.config, self.db).save_preferences({'study_type': 2})
        value = self.service.bootstrap()
        self.assertEqual(value['papers'][0]['title'], 'new paper')
        self.assertEqual(value['preferences']['study_type'], 2)
        self.assertEqual(value, self.service._build_bootstrap())

    def test_shared_library_writes_from_another_workspace_refresh_bank(self):
        other = self.root/'other'
        config = AppConfig(self.root, other, self.root/'dist', other/'learning.db',
                           library=self.config.library_dir)
        db = Database(config)
        db.initialize()
        # Exercise both rollback-journal and WAL commits; only the OTHER personal
        # DB and shared library change, so watching our personal DB is insufficient.
        for mode in ('DELETE', 'WAL'):
            self.service.close()
            with closing(sqlite3.connect(self.config.library_database)) as conn:
                conn.execute('PRAGMA journal_mode='+mode)
            before = self.service.bootstrap()
            LibraryService(config, db).import_text({'questions': [{'id': mode, 'stem': 'shared update'}]})
            after = self.service.bootstrap()
            self.assertEqual(len(after['bank']), len(before['bank'])+1)
            self.assertEqual(after, self.service._build_bootstrap())

    def test_commit_during_build_is_not_cached_under_new_revision(self):
        build = self.service._build_bootstrap
        def changing_build():
            value = build()
            PaperService(self.config, self.db).create({'title': 'concurrent commit'})
            return value
        with patch.object(self.service, '_build_bootstrap', side_effect=changing_build):
            self.assertEqual(self.service.bootstrap()['papers'], [])
        self.assertEqual(self.service.bootstrap()['papers'][0]['title'], 'concurrent commit')


if __name__ == '__main__':
    unittest.main()
