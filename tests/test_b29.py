import json
import sqlite3
import unittest
from app.titles import paper_title
from app.learning.practice_presentation import practice_label


class DisplayTitleTests(unittest.TestCase):
    def test_volume_names_preserve_suffix_and_unrelated_title(self):
        for old in ('2026数学一','2026年数一','2026 数学 1'):
            self.assertEqual(paper_title(old),'2026年数一')
        self.assertEqual(paper_title('2021数学二 重做'),'2021年数二 重做')
        self.assertEqual(paper_title('2023数三'),'2023年数三')
        self.assertEqual(paper_title('期中练习'),'期中练习')

    def test_captured_source_and_real_ordinals_distinguish_questions(self):
        with sqlite3.connect(':memory:') as conn:
            source=dict(collection_label='张宇1000题',book=dict(part='强化篇',chapter='第1章',number='3'))
            self.assertEqual(practice_label(conn,'hash-id',payload={'source_metadata':source}),
                             '张宇1000题 · 强化篇 第1章 · 第3题')
            self.assertEqual(practice_label(conn,'s02-hash',snapshot={'source':dict(year='2026',math_type=1,number=10)}),
                             '2026年数一 · 第10题')
            self.assertEqual(practice_label(conn,'math2-2021-03'),'2021年数二 · 第3题')
            self.assertEqual(practice_label(conn,'id',payload={'skill_label':'链式法则'},number=2),
                             '链式法则 · 第2题')

    def test_overview_titles_use_frozen_navigation_not_changed_library(self):
        import test_execution_v2 as execution
        from app.learning.loop import submit_probe,assess_attempt
        from app.bank.access import reveal
        from app.main import create_app
        from fastapi.testclient import TestClient
        import database_fixture as server
        f=execution.ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        source=dict(book=dict(part='强化篇',chapter='第1章',number='3'))
        f.conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(json.dumps(source),execution.prepared.BANK));f.conn.commit()
        f.save_selection()
        probe=f.conn.execute('SELECT * FROM diagnostic_probes WHERE bank_id=?',(execution.prepared.BANK,)).fetchone()
        reveal(f.conn,execution.prepared.BANK,'question',True)
        aid=submit_probe(f.conn,probe['id'],{'response':'work'})['attempt_id']
        assess_attempt(f.conn,aid,{'author':'fixture','correct':False,'feedback':'结论已核对。'})
        source['book']['number']='99'
        f.conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(json.dumps(source),execution.prepared.BANK))
        f.conn.execute("UPDATE papers SET title='2026数学一'");f.conn.commit()
        with TestClient(create_app(server.config(),agent_factory=None),base_url='http://127.0.0.1') as http:
            value=http.get('/api/profile/overview');self.assertEqual(value.status_code,200,value.text)
            feedback=value.json()['feedback']['recent_items'][0]
            self.assertIn('强化篇 第1章 · 第3题',feedback['title']);self.assertNotIn('99',feedback['title'])
            mistake=next(m for m in value.json()['recent_mistakes'] if m['attempt_id']==aid)
            self.assertEqual(mistake['label'],feedback['title'])
            self.assertEqual(http.get('/api/papers/paper-test').json()['paper']['title'],'2026年数一')
            self.assertEqual(http.get('/api/papers?limit=20').json()['items'][0]['title'],'2026年数一')
            self.assertEqual(http.get('/api/papers').json()['papers'][0]['title'],'2026年数一')
            self.assertEqual(http.get('/api/bootstrap').json()['papers'][0]['title'],'2026年数一')
        self.assertEqual(f.conn.execute('SELECT title FROM papers').fetchone()[0],'2026数学一')

    def test_free_practice_feedback_uses_captured_exam_number(self):
        import test_free_practice as free
        f=free.FreePracticeTests();f.setUp();self.addCleanup(f.doCleanups)
        f.conn.execute("UPDATE bank_identity SET year='2026',math_type=1,number=10 WHERE bank_id='bank-test'");f.conn.commit()
        response=f.submit(choice='A');self.assertEqual(response.status_code,200,response.text)
        value=f.http.get('/api/profile/overview');self.assertEqual(value.status_code,200,value.text)
        title=value.json()['feedback']['recent_items'][0]['title']
        self.assertEqual(title,'2026年数一 · 第10题')
        self.assertEqual(value.json()['recent_mistakes'][0]['label'],title)
