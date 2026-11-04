import time,unittest
from unittest.mock import patch
from app.services.knowledge_links import KnowledgeLinksService
from app.storage.knowledge_reads import navigation_snapshot

class PersistentNavigationTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_links import KnowledgeLinksTests
        self.f=KnowledgeLinksTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.conn=self.f.conn

    def test_restart_reuses_persistent_validation_and_copies_no_library_tables(self):
        before=self.f.service.summary()
        fresh=KnowledgeLinksService(self.f.config,self.f.db)
        with patch('app.bank.annotations.current',side_effect=AssertionError('full revalidation')):
            start=time.monotonic();self.assertEqual(fresh.summary(),before)
            self.assertLess(time.monotonic()-start,2)
        with navigation_snapshot(self.f.db) as copied:
            self.assertIsNone(copied.execute("SELECT 1 FROM main.sqlite_master WHERE name='bank_questions'").fetchone())
            self.assertEqual(copied.execute('SELECT count(*) FROM library.bank_questions').fetchone()[0],len(self.f.ids))

    def test_runtime_prepares_persistent_index_before_ui_without_warmup_thread(self):
        from app.runtime import AppRuntime
        def prepared(data):self.assertTrue((data/'navigation-index.db').is_file())
        with patch('app.runtime.interrupt_old_progress',side_effect=prepared):
            runtime=AppRuntime(self.f.config,agent_factory=None)
            try:
                runtime.start()
                self.assertTrue((self.f.config.data/'navigation-index.db').is_file())
                self.assertFalse(hasattr(runtime.frontend,'_warmup_thread'))
                with patch.object(runtime.knowledge_links,'_build_bank_item',side_effect=AssertionError('repeat full validation')):
                    self.assertEqual(runtime.frontend.topic('GS-04-001')['topic']['id'],'GS-04-001')
            finally:runtime.close()

    def test_only_changed_bank_rows_and_aliases_revalidate(self):
        self.f.service.summary();fresh=KnowledgeLinksService(self.f.config,self.f.db)
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('added','synthetic','New text','now')");self.conn.commit()
        with patch.object(fresh,'_build_bank_item',wraps=fresh._build_bank_item) as build:
            fresh.summary();self.assertEqual([c.args[1]['id'] for c in build.call_args_list],['added'])
        self.conn.execute('UPDATE bank_questions SET stem=stem WHERE id=?',(self.f.ids[0],));self.conn.commit()
        with patch.object(fresh,'_build_bank_item',side_effect=AssertionError('no-op write')):fresh.summary()
        self.conn.execute('UPDATE preferences SET payload=payload WHERE id=1');self.conn.commit()
        with patch.object(fresh,'_build_bank_item',side_effect=AssertionError('personal write')):fresh.summary()
        self.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('Changed answer',self.f.ids[0]));self.conn.commit()
        with patch.object(fresh,'_build_bank_item',wraps=fresh._build_bank_item) as build:
            value=fresh.summary();self.assertEqual({c.args[1]['id'] for c in build.call_args_list},set(self.f.ids))
        self.assertEqual(value['nodes']['GS-04-001']['ready'],0)

    def test_identity_link_change_invalidates_only_connected_components(self):
        from app.bank.access import init_access
        for bid in ('joinable','unrelated'):
            self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES(?,'synthetic',?,'now')",(bid,bid))
        init_access(self.conn);self.conn.commit();self.f.service.summary()
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)',(self.f.ids[0],'joinable','isolated identity test'))
        self.conn.commit();fresh=KnowledgeLinksService(self.f.config,self.f.db)
        with patch.object(fresh,'_build_bank_item',wraps=fresh._build_bank_item) as build:
            fresh.summary()
        self.assertEqual({call.args[1]['id'] for call in build.call_args_list},{*self.f.ids,'joinable'})

