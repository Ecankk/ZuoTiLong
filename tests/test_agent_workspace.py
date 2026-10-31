import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.agent.workspace import bank_catalog, topic_audit
from app.bank.access import init_access, save_preferences


class AgentWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.conn = sqlite3.connect(":memory:")
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript("""
          CREATE TABLE bank_questions(id TEXT PRIMARY KEY,stem TEXT,fingerprint_json TEXT);
          CREATE TABLE bank_resources(bank_id TEXT PRIMARY KEY,metadata_json TEXT,question_path TEXT,analysis_path TEXT,answer_path TEXT);
        """)
        (ROOT / "tmp").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "tmp", prefix="agent-workspace-test-")
        self.root = Path(self.temp.name)
        (self.root / "question.png").write_bytes(b"fixture")
        for bid, topic in [("a", "第二类曲面积分"), ("b", "第二类曲线积分"), ("c", "二次型")]:
            self.conn.execute("INSERT INTO bank_questions VALUES(?,?,?)", (bid, "metadata only", '{"objects":["topic"]}'))
            self.conn.execute("INSERT INTO bank_resources VALUES(?,?,?,?,?)", (bid, json.dumps({"knowledge_point":topic}), "question.png", "missing-analysis.png", None))
        init_access(self.conn)

    def tearDown(self):
        self.conn.close()
        self.assertEqual(self.root.resolve().parent, (ROOT / "tmp").resolve())
        self.temp.cleanup()

    def test_catalog_supports_unfiltered_browsing_pagination_and_multiple_topics(self):
        page = bank_catalog(self.conn, self.root, limit=1)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["next_offset"], 1)
        next_page = bank_catalog(self.conn, self.root, offset=page["next_offset"], limit=2)
        self.assertEqual({p['id'] for p in page['items']+next_page['items']},{'a','b','c'})
        self.assertIsNone(next_page["next_offset"])
        combined = bank_catalog(self.conn, self.root, topics=["曲面", "二次"])
        self.assertEqual({p["id"] for p in combined["items"]}, {"a", "c"})

    def test_resources_are_explicit_and_not_claimed_verified(self):
        q = bank_catalog(self.conn, self.root, bank_id="a")["items"][0]
        self.assertTrue(q["resources"]["question"]["exists"])
        self.assertFalse(q["resources"]["analysis"]["exists"])
        self.assertIsNone(q["resources"]["answer"])
        self.assertEqual(q["review_status"], "not_established_by_catalog")
        self.assertNotIn("score", q)

    def test_navigation_can_find_known_operations_without_treating_labels_as_full_text(self):
        self.conn.execute('UPDATE bank_questions SET fingerprint_json=? WHERE id=?',
                          (json.dumps({'operations':['散度计算']},ensure_ascii=False),'a'))
        result=bank_catalog(self.conn,self.root,topics=['散度'])
        self.assertEqual([r['id'] for r in result['items']],['a'])
        self.assertEqual(result['items'][0]['source_topic'],'第二类曲面积分')
        self.assertNotIn('rank',result['items'][0])
        self.assertIn('指纹',result['topic_filter_scope'])

    def test_outside_resource_and_invalid_page_are_rejected(self):
        with self.assertRaises(ValueError):
            bank_catalog(self.conn, self.root, limit=0)
        self.conn.execute("UPDATE bank_resources SET question_path='../outside.png' WHERE bank_id='a'")
        with self.assertRaises(ValueError):
            bank_catalog(self.conn, self.root, bank_id="a")

    def test_audit_distinguishes_source_labels_from_finer_fields_without_writing(self):
        before = self.conn.total_changes
        audit = topic_audit(self.conn)
        self.assertEqual(audit["question_count"], 3)
        self.assertEqual(audit["source_topic_count"], 3)
        self.assertEqual(audit["questions_with_operation_or_micro_skill_fields"], 0)
        self.assertEqual(self.conn.total_changes, before)

    def add_categories(self):
        for category in (1,2,3):
            for number in range(1,5):
                bid=f'math{category}-2025-{number:02d}'
                self.conn.execute('INSERT INTO bank_questions VALUES(?,?,?)',(bid,'fixture','{}'))
                self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',
                    (bid,json.dumps({'knowledge_point':'shared topic'}),'question.png',None,None))
        init_access(self.conn)

    def test_catalog_whole_pool_has_complete_stable_pagination(self):
        self.add_categories();before=self.conn.total_changes
        first=bank_catalog(self.conn,self.root,topics=['shared'],limit=3)
        self.assertEqual(first['counts_by_math_type'],{'1':4,'2':4,'3':4})
        ids=[];offset=0
        while True:
            page=bank_catalog(self.conn,self.root,topics=['shared'],limit=3,offset=offset)
            ids.extend(e['id'] for e in page['items'])
            if page['next_offset'] is None:break
            offset=page['next_offset']
        self.assertEqual(len(ids),12)
        self.assertEqual(len(set(ids)),12)
        self.assertEqual(ids,[e['id'] for e in bank_catalog(self.conn,self.root,topics=['shared'],limit=100)['items']])
        self.assertEqual(self.conn.total_changes,before)

    def test_category_filter_and_reservation_are_respected_before_browsing_counts(self):
        self.add_categories()
        save_preferences(self.conn,{'study_type':1,'reserved':[{'math_type':2,'year':'2025'}]})
        result=bank_catalog(self.conn,self.root,topics=['shared'])
        self.assertEqual(result['counts_by_math_type'],{'1':4,'3':4})
        self.assertEqual({e['math_type'] for e in result['items']},{1,3})
        result=bank_catalog(self.conn,self.root,topics=['shared'],math_types=[3])
        self.assertEqual(result['counts_by_math_type'],{'3':4})
        self.assertTrue(all(e['math_type']==3 for e in result['items']))

    def test_browsing_order_and_examples_do_not_depend_on_exam_category(self):
        self.add_categories();before=self.conn.total_changes
        audit=topic_audit(self.conn)
        topic=next(t for t in audit['topics'] if t['label']=='shared topic')
        self.assertEqual(topic['counts_by_math_type'],{'1':4,'2':4,'3':4})
        self.assertEqual(self.conn.total_changes,before)
        original_ids=[e['id'] for e in bank_catalog(self.conn,self.root,topics=['shared'],limit=100)['items']]
        self.conn.execute('UPDATE bank_identity SET math_type=3-math_type WHERE math_type IN (1,2)')
        self.assertEqual(original_ids,[e['id'] for e in bank_catalog(self.conn,self.root,topics=['shared'],limit=100)['items']])
        updated=next(t for t in topic_audit(self.conn)['topics'] if t['label']=='shared topic')
        self.assertEqual(topic['examples'],updated['examples'])


if __name__ == "__main__":
    unittest.main()
