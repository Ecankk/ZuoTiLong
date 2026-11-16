import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from scripts.identity_similarity_scan import normalize,parse_exam_claims,score,scan


class SimilarityScanTests(unittest.TestCase):
    def test_exam_claim_parser_preserves_categories_and_only_explicit_numbers(self):
        self.assertEqual(
            parse_exam_claims('1987年·数一；880第三章基础填空16'),
            [{'year':1987,'math_type':1,'number':None}],
        )
        self.assertEqual(
            parse_exam_claims('2026数一（4）'),
            [{'year':2026,'math_type':1,'number':4}],
        )
        self.assertEqual(
            parse_exam_claims('2009数二三（二16、三16）'),
            [
                {'year':2009,'math_type':2,'number':16},
                {'year':2009,'math_type':3,'number':16},
            ],
        )

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

    def test_exam_claims_join_draft_and_report_resolution(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);library=root/'library';library.mkdir();input_path=root/'records.jsonl'
            conn=sqlite3.connect(library/'library.db')
            try:
                conn.executescript('''
                CREATE TABLE bank_questions(id TEXT PRIMARY KEY,source TEXT,stem TEXT,answer TEXT,explanation TEXT,tags_json TEXT,collection_id TEXT,math_types_json TEXT);
                CREATE TABLE bank_resources(bank_id TEXT PRIMARY KEY,metadata_json TEXT,question_path TEXT,analysis_path TEXT,answer_path TEXT);
                CREATE TABLE bank_source_records(bank_id TEXT PRIMARY KEY,record_json TEXT);
                CREATE TABLE bank_identity(bank_id TEXT PRIMARY KEY,year INTEGER,math_type INTEGER,number INTEGER);
                ''')
                conn.execute("INSERT INTO bank_questions VALUES('math1-2026-04','S01','题干','','','[]','zhenti','[]')")
                conn.execute("INSERT INTO bank_resources VALUES('math1-2026-04','{}','','','')")
                conn.execute("INSERT INTO bank_identity VALUES('math1-2026-04',2026,1,4)")
                conn.commit()
            finally:
                conn.close()
            def record(uid,text):
                return {'schema':'mathlens.bank-record/v1','source_id':'S02','revision':'r','source_uid':uid,
                        'locator':{'path':'x','pointer':'/0','source_sha256':'0'*64},'exam_year':None,'math_type':None,'number':None,
                        'question_type':'choice','max_score':None,'stem':{'text':'题干','sha256':'0'*64,'images':[]},
                        'answer':{'text':'','sha256':'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855','images':[]},
                        'analysis':{'text':'','sha256':'e3b0c44298fc1c149afbf4c8999b934ca495991b7852b855','images':[]},
                        'options':[],'original':{'source_text':text,'record':{},'sha256':'0'*64},'tags':[]}
            # The second claim has a year/category but no explicit original question number.
            input_path.write_text('\n'.join(json.dumps(r,ensure_ascii=False) for r in (
                record('resolved','2026数一（4）'), record('unresolved','1987年·数一；880第三章基础填空16'))),encoding='utf8')
            result=scan(input_path,library)
            self.assertEqual(result['exam_claim_count'],2)
            self.assertEqual(result['exam_claim_resolved'],1)
            self.assertEqual(result['exam_claim_unresolved'],1)
            self.assertEqual(result['exam_claim_samples'][0]['reason'],'exam_claim')
            self.assertEqual(result['exam_claim_samples'][0]['bank_id'],'math1-2026-04')
            self.assertEqual(result['exam_claim_unresolved_samples'][0]['reason'],'exam_claim_unresolved')
            self.assertEqual({e['decision'] for e in result['identities_draft']['entries']},{'pending'})
            self.assertEqual(result['identities_draft']['entries'][0]['exam_claims'][0]['reason'],'exam_claim')
            self.assertEqual(result['identities_draft']['entries'][1]['exam_claims'][0]['reason'],'exam_claim_unresolved')
