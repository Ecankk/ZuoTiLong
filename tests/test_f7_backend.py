import json,unittest
from unittest.mock import patch
from app.runtime import AppRuntime
from app.bank.access import public_bank


class F7BackendTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_links import KnowledgeLinksTests
        self.f=KnowledgeLinksTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.conn=self.f.conn;self.rt=AppRuntime(self.f.config,agent_factory=None);self.addCleanup(self.rt.close)

    def test_resource_projection_reused_across_topics_and_invalidated_by_both_stores(self):
        self.rt.frontend.topic('GS-04-001')
        with patch.object(self.rt.knowledge_links,'resource_snapshot',side_effect=AssertionError('rebuild')):
            self.rt.frontend.topic('math1.calculus.differentiation')
            self.assertTrue(self.rt.frontend.bank(topic_id='GS-04-001')['total'])
        from app.bank.access import save_preferences
        save_preferences(self.conn,{'mask_same_type':False});self.conn.commit()
        with patch.object(self.rt.knowledge_links,'_bank_index',side_effect=AssertionError('unnecessary material check')):
            self.rt.frontend.bank(topic_id='GS-04-001')
        self.conn.execute("UPDATE bank_questions SET stem=stem||' changed'");self.conn.commit()
        self.assertEqual(self.rt.frontend.bank(topic_id='GS-04-001')['total'],0)

    def test_hash_ids_sorted_by_exam_identity_and_text_analysis_permission(self):
        for bid,year,kind,number in [('z-hash',2026,1,1),('a-hash',2026,1,22),('m-hash',2025,2,3)]:
            self.conn.execute('INSERT INTO bank_questions(id,source,stem,explanation,created_at) VALUES(?,?,?,?,?)',(bid,'S02','synthetic question','synthetic reference','now'))
            self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,NULL,NULL)',(bid,json.dumps({'schema':'mathlens.bank-record/v1'}),''))
            self.conn.execute('INSERT INTO bank_identity VALUES(?,?,?,?,NULL)',(bid,kind,str(year),number))
        self.conn.commit()
        values=self.rt.frontend.bank(limit=2)['items']
        self.assertEqual([v['id'] for v in values],['z-hash','a-hash'])
        self.assertEqual(values[0]['analysis_text'],'synthetic reference')
        self.assertNotIn('analysis_text',public_bank(self.conn,'z-hash'))
        self.assertEqual(self.rt.frontend.bank(offset=2,limit=1)['items'][0]['id'],'m-hash')

    def test_tree_is_complete_and_has_no_definitions_or_personal_projection(self):
        with patch.object(self.rt.knowledge_links,'_bank_index',side_effect=AssertionError('bank scan')):
            value=self.rt.knowledge_catalog.tree()
        self.assertEqual(value['total'],len(value['items']))
        node=next(n for n in value['items'] if n['id']=='GS-04-001')
        self.assertNotIn('definition',node);self.assertIn('aliases',node);self.assertEqual(node['child_count'],0)
