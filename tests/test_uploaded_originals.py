import json,unittest
import test_learning_loop as fixtures
import test_execution_v2 as execution
from app.bank.originals import uploaded_originals


class UploadedOriginalTests(unittest.TestCase):
    def test_whole_uploaded_exam_and_aliases_even_archived_or_not_segmented(self):
        f=fixtures.LearningLoopTests();f.setUp();self.addCleanup(f.tearDown);conn=f.conn
        conn.execute("INSERT INTO papers(id,title,source_path,archived_at,created_at) VALUES('old','2026年数一','papers/missing.pdf','now','now')")
        for bid,number in [('s02-q10',10),('another-source',10),('unrelated',11)]:
            conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES(?,'fixture','text','now')",(bid,))
            conn.execute('INSERT INTO bank_identity VALUES(?,?,?,?,NULL)',(bid,1 if bid!='unrelated' else 2,'2026',number))
        conn.execute("INSERT INTO bank_links VALUES('s02-q10','bank-test','confirmed synthetic alias')")
        before=conn.execute('SELECT count(*) FROM bank_views').fetchone()[0]
        result=uploaded_originals(conn)
        for bid in ('s02-q10','another-source','bank-test'):self.assertEqual(result[bid],['old'])
        self.assertNotIn('unrelated',result)
        self.assertEqual(conn.execute('SELECT count(*) FROM bank_views').fetchone()[0],before)
        conn.execute("INSERT INTO questions(id,paper_id,number,match_bank_id,created_at) VALUES('q','paper-test','1','unrelated','now')")
        self.assertIn('paper-test',uploaded_originals(conn)['unrelated'])

    def test_other_uploaded_paper_excluded_during_capture_and_late_delivery(self):
        for late in (False,True):
            with self.subTest(late=late):
                f=execution.ExecutionTests();f.setUp()
                try:
                    if late:
                        _,scope=f.selection();value=f.selection_payload(scope)
                    f.conn.execute("INSERT INTO papers(id,title,source_path,created_at) VALUES('other','2020 数学二','papers/other.pdf','now')");f.conn.commit()
                    if late:
                        from app.learning.selection import normalize
                        with self.assertRaisesRegex(ValueError,'已上传试卷原题.*other'):normalize(f.conn,f.data,f.task,value['result'])
                    else:
                        _,scope=f.selection()
                        self.assertNotIn(execution.prepared.BANK,scope['candidates'])
                        self.assertFalse(any(execution.prepared.BANK in t['candidate_ids'] for t in scope['targets']))
                finally:f.doCleanups()
