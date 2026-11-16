import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.identity_similarity_scan import normalize,score,scan


class SimilarityScanTests(unittest.TestCase):
    def test_latex_normalization_and_option_score(self):
        self.assertEqual(normalize(r'第 3 题：\left( x \leqslant 1 \right)'), 'x<=1')
        value=score({'stem':r'求 $x^2+1$', 'options':['A. 1','B. 2']},
                    {'stem':'求 x^2+1', 'options':['1','2']})
        self.assertGreaterEqual(value[0],.6)

    def test_scan_returns_top3_and_pending_identity_draft_without_writes(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);library=root/'library';library.mkdir();input_path=root/'records.jsonl';out=root/'report.json'
            conn=sqlite3.connect(library/'library.db')
            try:
                conn.executescript('''CREATE TABLE bank_questions(id TEXT PRIMARY KEY,source TEXT,stem TEXT,answer TEXT,explanation TEXT,tags_json TEXT,collection_id TEXT,math_types_json TEXT);
                CREATE TABLE bank_resources(bank_id TEXT PRIMARY KEY,metadata_json TEXT,question_path TEXT,analysis_path TEXT,answer_path TEXT);
                CREATE TABLE bank_source_records(bank_id TEXT PRIMARY KEY,record_json TEXT);''')
                conn.execute("INSERT INTO bank_questions VALUES('math1-2000-01','S01','求 x^2+1','A','','[]','zhenti','[]')")
                conn.execute("INSERT INTO bank_resources VALUES('math1-2000-01','{}','','','')")
                conn.commit()
            finally:
                conn.close()
            record={'schema':'mathlens.bank-record/v1','source_id':'S02','revision':'r','source_uid':'u1',
                    'locator':{'path':'x','pointer':'/0','source_sha256':'0'*64},'exam_year':None,'math_type':None,'number':None,
                    'question_type':'choice','max_score':None,'stem':{'text':'求 x^2+1','sha256':'0'*64,'images':[]},
                    'answer':{'text':'','sha256':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','images':[]},
                    'analysis':{'text':'','sha256':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','images':[]},
                    'options':[],'original':{'source_text':'','record':{},'sha256':'0'*64},'tags':[]}
            input_path.write_text(json.dumps(record),encoding='utf8')
            before=(library/'library.db').read_bytes();result=scan(input_path,library);after=(library/'library.db').read_bytes()
            self.assertEqual(result['input_count'],1);self.assertEqual(len(result['candidates'][0]['candidates']),1)
            self.assertEqual(result['identities_draft']['entries'][0]['decision'],'pending');self.assertEqual(before,after)
