import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent_workspace import bank_catalog, topic_audit


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

    def tearDown(self):
        self.conn.close()
        self.assertEqual(self.root.resolve().parent, (ROOT / "tmp").resolve())
        self.temp.cleanup()

    def test_catalog_supports_unfiltered_browsing_pagination_and_multiple_topics(self):
        page = bank_catalog(self.conn, self.root, limit=1)
        self.assertEqual(page["total"], 3)
        self.assertEqual(page["next_offset"], 1)
        next_page = bank_catalog(self.conn, self.root, offset=page["next_offset"], limit=2)
        self.assertEqual([p["id"] for p in next_page["items"]], ["b", "c"])
        self.assertIsNone(next_page["next_offset"])
        combined = bank_catalog(self.conn, self.root, topics=["曲面", "二次"])
        self.assertEqual([p["id"] for p in combined["items"]], ["a", "c"])

    def test_resources_are_explicit_and_not_claimed_verified(self):
        q = bank_catalog(self.conn, self.root, bank_id="a")["items"][0]
        self.assertTrue(q["resources"]["question"]["exists"])
        self.assertFalse(q["resources"]["analysis"]["exists"])
        self.assertIsNone(q["resources"]["answer"])
        self.assertEqual(q["review_status"], "not_established_by_catalog")
        self.assertNotIn("score", q)

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


if __name__ == "__main__":
    unittest.main()
