import copy
import hashlib
from io import BytesIO
from email.message import Message
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import urlparse

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
import server
from learning_loop import apply_report, assess_attempt, loop_snapshot, submit_probe, revise_assessment, supplement_attempt, replace_probe
from answer_images import save_answer_image
from bank_access import init_access,reveal
from pdf_pipeline import extract_pdf, segment_pages, _bank_score
import pymupdf as fitz


class LearningLoopTests(unittest.TestCase):
    def setUp(self):
        (ROOT/'tmp').mkdir(exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='loop-test-')
        self.root=Path(self.temp.name)
        self.previous=(server.DATA,server.PAPERS_DIR,server.DB_PATH)
        server.DATA=self.root;server.PAPERS_DIR=self.root/'papers';server.DB_PATH=self.root/'test.db'
        server.init_db();self.conn=server.connect()
        self.pdf=server.PAPERS_DIR/'fixture.pdf'
        with fitz.open() as d:
            p=d.new_page();p.insert_text((72,72),'1. A question.\n2. Another question.');d.save(str(self.pdf))
        self.digest=hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.conn.execute("INSERT INTO papers(id,title,source_path,created_at) VALUES(?,?,?,?)",('paper-test','test',str(self.pdf.relative_to(ROOT)),'now'))
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('bank-test','test','question','now')")
        self.conn.execute("INSERT INTO bank_resources VALUES('bank-test','{}','unused.png',NULL,NULL)")
        init_access(self.conn);reveal(self.conn,'bank-test','question',True)
        self.conn.commit()
        self.report={'author':'test-agent','method':'test evidence','source_sha256':self.digest,'expected_count':2,
            'questions':[{'number':n,'stem':f'Question {n}','regions':[{'page':1,'bbox':[20,30+n*80,550,100+n*80],'role':'question_and_work'}],
                          'correctness':'wrong','observation':'visible mistake','hypotheses':[],
                          'skill_events':[{'skill_id':'bounds','label':'bounds','kind':'exam_error'}]} for n in [1,2]],
            'probes':[{'id':'probe-test','question_number':1,'bank_id':'bank-test','skill_id':'bounds','skill_label':'bounds',
                       'prompt':'compute','expected':'2/3','accepted':['2/3'],'priority':1}]}

    def tearDown(self):
        self.conn.close();server.DATA,server.PAPERS_DIR,server.DB_PATH=self.previous
        self.assertEqual(self.root.resolve().parent,(ROOT/'tmp').resolve())
        self.temp.cleanup()

    def apply(self):
        result=apply_report(self.conn,'paper-test',self.report,ROOT);self.conn.commit();return result

    def test_source_hash_and_all_questions_are_required(self):
        bad=copy.deepcopy(self.report);bad['source_sha256']='0'*64
        with self.assertRaises(ValueError): apply_report(self.conn,'paper-test',bad,ROOT)
        bad=copy.deepcopy(self.report);bad['questions'].pop()
        with self.assertRaises(ValueError): apply_report(self.conn,'paper-test',bad,ROOT)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],0)

    def test_regions_are_checked_before_writing(self):
        bad=copy.deepcopy(self.report);bad['questions'][0]['regions'][0]['bbox']=[0,0,2000,2000]
        with self.assertRaises(ValueError): apply_report(self.conn,'paper-test',bad,ROOT)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],0)

    def test_report_reimport_preserves_answers(self):
        self.apply();probe_id='paper-test-probe-test'
        submit_probe(self.conn,probe_id,{'response':'my reasoning'})
        self.conn.commit();self.apply()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM questions').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],1)

    def test_no_answer_leak_before_submission(self):
        self.apply();probe=loop_snapshot(self.conn)['probes'][0]
        for key in ['expected','accepted','rubric','solution_note','payload_json']:
            self.assertNotIn(key,probe)

    def test_photo_only_answer_is_durable_idempotent_and_waits_for_agent(self):
        from PIL import Image
        raw=BytesIO();Image.new('RGB',(60,40),'white').save(raw,format='PNG')
        asset=save_answer_image(self.conn,self.root,raw.getvalue())
        self.apply();pid='paper-test-probe-test'
        body={'response':'','image_ids':[asset['id']],'request_id':'22345678-1234-1234-1234-123456789012'}
        result=submit_probe(self.conn,pid,body);self.conn.commit()
        self.assertIsNone(result['assessment'])
        self.assertEqual(result['status'],'awaiting_assessment')
        self.assertTrue(submit_probe(self.conn,pid,body)['reused'])
        attempt=loop_snapshot(self.conn)['probes'][0]['attempts'][0]
        self.assertEqual(attempt['image_ids'],[asset['id']])
        self.assertEqual(attempt['response'],'')
        with self.assertRaises(ValueError):submit_probe(self.conn,pid,{**body,'image_ids':[],'response':'2/3'})
        # Even a matching typed result cannot automatically grade accompanying handwritten work.
        another=submit_probe(self.conn,pid,{'response':'2/3','image_ids':[asset['id']]})
        self.assertIsNone(another['assessment'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_success'").fetchone()[0],0)

    def test_unknown_expression_waits_for_agent_not_marked_wrong(self):
        self.apply();result=submit_probe(self.conn,'paper-test-probe-test',{'response':'an equivalent expression'})
        self.assertEqual(result['status'],'awaiting_assessment')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],2)
        assess_attempt(self.conn,result['attempt_id'],{'correct':True,'feedback':'equivalent','author':'test-agent'})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_success'").fetchone()[0],1)

    def test_assessment_revision_and_supplement_keep_audit_history(self):
        self.apply()
        attempt = submit_probe(self.conn, 'paper-test-probe-test', {'response': 'uncertain'})['attempt_id']
        assess_attempt(self.conn, attempt, {'correct': False, 'feedback': '边界条件遗漏', 'author': 'agent'})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_failure'").fetchone()[0], 1)
        revise_assessment(self.conn, attempt, {'correct': True, 'feedback': '补充后条件完整', 'author': 'agent'}, '重新核对了手写步骤')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_failure'").fetchone()[0], 0)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_success'").fetchone()[0], 1)
        supplement_attempt(self.conn, attempt, {'response': '补充边界说明', 'reason': '用户补充遗漏步骤'})
        self.assertIsNone(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?', (attempt,)).fetchone()[0])
        self.assertGreaterEqual(self.conn.execute('SELECT count(*) FROM record_versions').fetchone()[0], 2)

    def test_replacing_probe_retires_old_task(self):
        self.apply()
        result = replace_probe(self.conn, 'paper-test-probe-test', {
            'reason': '原题未能区分建模环节，需要换成更合适的检验',
            'changes': {'skill_id': 'entry', 'skill_label': 'entry', 'prompt': '先写出切入关系', 'discriminates': '能否从条件选方法'},
        })
        self.assertNotEqual(result['probe_id'], 'paper-test-probe-test')
        self.assertTrue(self.conn.execute('SELECT 1 FROM retired_probes WHERE probe_id=?', ('paper-test-probe-test',)).fetchone())
        self.assertEqual(len(loop_snapshot(self.conn)['probes']), 1)
        self.assertEqual(loop_snapshot(self.conn)['probes'][0]['id'], result['probe_id'])

    def test_uploaded_photo_http_roundtrip_and_invalid_file_rollback(self):
        from PIL import Image
        raw=BytesIO();Image.new('RGB',(60,40),'white').save(raw,format='PNG')
        def upload(contents):
            boundary='photo-upload-test'
            parts=[(f'--{boundary}\r\nContent-Disposition: form-data; name="files"; filename="../../private.png"\r\nContent-Type: image/png\r\n\r\n').encode()+data+b'\r\n' for data in contents]
            body=b''.join(parts)+f'--{boundary}--\r\n'.encode()
            handler=server.Handler.__new__(server.Handler)
            handler.headers=Message();handler.headers['Content-Type']=f'multipart/form-data; boundary={boundary}';handler.headers['Content-Length']=str(len(body))
            handler.rfile=BytesIO(body);result={}
            handler.send_json=lambda payload,status=200:result.update(payload=payload,status=int(status))
            handler.upload_answer_images()
            return handler,result
        with self.assertRaises(ValueError):upload([raw.getvalue(),b'invalid'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM answer_images').fetchone()[0],0)
        handler,result=upload([raw.getvalue()])
        self.assertEqual(result['status'],201)
        image=result['payload']['images'][0];served=[]
        handler.send_file=lambda path,mime:served.append((path,mime))
        handler.api_get(urlparse(image['url']))
        self.assertTrue(served[0][0].is_relative_to(self.root/'answer-images'))
        self.assertEqual(served[0][1],'image/jpeg')
        self.assertNotIn('path',image)
        handler.api_get(urlparse('/api/answer-images/image-'+'0'*32))
        self.assertEqual(result['status'],404)

    def test_saved_photo_feedback_reuses_attempt_and_preserves_context(self):
        from PIL import Image
        from unittest.mock import Mock
        raw=BytesIO();Image.new('RGB',(60,40),'white').save(raw,format='PNG')
        asset=save_answer_image(self.conn,self.root,raw.getvalue())
        self.apply();pid='paper-test-probe-test'
        attempt=submit_probe(self.conn,pid,{'response':'','image_ids':[asset['id']]})
        self.conn.commit()
        bridge=Mock(connected=True);bridge.snapshot.return_value={'turns':[]};handler=server.Handler.__new__(server.Handler)
        with patch.object(server,'BRIDGE',bridge):
            handler.request_probe_feedback(self.conn,pid,attempt['attempt_id'])
            first=bridge.submit.call_args.args
            handler.request_probe_feedback(self.conn,pid,attempt['attempt_id'])
            self.assertEqual(bridge.submit.call_args.args,first)
            with self.assertRaises(ValueError):handler.request_probe_feedback(self.conn,'another-probe',attempt['attempt_id'])
        self.assertEqual(first[2]['screen']['probe_id'],pid)
        self.assertEqual(first[2]['question_id'],'paper-test-q-01')
        self.assertEqual(first[3],[asset['id']])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM learning_events WHERE kind='probe_success'").fetchone()[0],0)

    def test_submit_is_idempotent_and_not_mastery(self):
        self.apply();body={'response':'2/3','request_id':'12345678-1234-1234-1234-123456789012'}
        submit_probe(self.conn,'paper-test-probe-test',body)
        result=submit_probe(self.conn,'paper-test-probe-test',body)
        self.assertTrue(result['reused'])
        snap=loop_snapshot(self.conn)
        self.assertEqual(len(snap['probes'][0]['attempts']),1)
        self.assertNotIn('掌握',snap['skills'][0]['state'])
        self.assertEqual(snap['skills'][0]['independent_probe_successes'],1)

    def test_seen_solution_is_not_independent_evidence(self):
        self.apply();self.conn.execute("INSERT INTO bank_exposures VALUES('bank-test','now')")
        submit_probe(self.conn,'paper-test-probe-test',{'response':'2/3','answer_exposed':False})
        self.assertEqual(loop_snapshot(self.conn)['skills'][0]['independent_probe_successes'],0)

    def test_failed_report_rolls_back_in_caller_transaction(self):
        bad=copy.deepcopy(self.report);bad['probes'][0]['bank_id']='missing'
        with self.assertRaises(ValueError):
            with self.conn: apply_report(self.conn,'paper-test',bad,ROOT)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM questions').fetchone()[0],0)

    def test_decimals_subquestions_and_page_boundaries(self):
        texts=['1. Evaluate 0.5 and 0.25.\n(1) A subpart.\n(2) Another subpart.\n2. Second main question.',
               '3. Third main question.']
        p=self.root/'segmentation.pdf'
        with fitz.open() as d:
            for text in texts:
                page=d.new_page();page.insert_text((72,72),text)
            d.save(str(p))
        result=extract_pdf(p,allow_ocr=False)
        self.assertEqual([q['number'] for q in result['questions']],['1','2','3'])
        self.assertIn('Second main question',result['questions'][1]['stem'])
        self.assertNotIn('Another subpart',result['questions'][1]['stem'])
        self.assertEqual([(q['page_start'],q['page_end']) for q in result['questions']],[(1,1),(1,1),(2,2)])
        self.assertNotEqual(result['questions'][0]['bbox'],result['questions'][1]['bbox'])

    def test_missing_middle_number_and_different_constraints(self):
        page={'page_number':1,'width':595,'height':840,'blocks':[
            {'text':'(1) First','bbox':[50,60,300,80]}, {'text':'(3) Third','bbox':[50,160,300,180]}]}
        questions,warnings=segment_pages([page],expected_count=3)
        self.assertEqual([q['number'] for q in questions],['1','3'])
        self.assertIn('2',warnings[0])
        self.assertLess(_bank_score('Find x^2=1. Only positive roots.',{'stem':'Find x^2=1.'}),.85)

    def upload(self,content):
        boundary='mathlens-test-boundary'
        body=(f'--{boundary}\r\nContent-Disposition: form-data; name="title"\r\n\r\n测试试卷\r\n'
              f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="paper.pdf"\r\nContent-Type: application/pdf\r\n\r\n').encode()+content+f'\r\n--{boundary}--\r\n'.encode()
        handler=server.Handler.__new__(server.Handler)
        handler.headers=Message();handler.headers['Content-Type']=f'multipart/form-data; boundary={boundary}';handler.headers['Content-Length']=str(len(body))
        handler.rfile=BytesIO(body);captured={}
        handler.send_json=lambda payload,status=200:captured.update(payload=payload,status=int(status))
        handler.import_paper();return captured

    def test_multipart_pdf_import_is_deduplicated(self):
        first=self.upload(self.pdf.read_bytes());self.assertEqual(first['status'],201)
        self.assertEqual(first['payload']['paper']['title'],'测试试卷')
        second=self.upload(self.pdf.read_bytes());self.assertTrue(second['payload']['reused'])
        self.assertEqual(first['payload']['paper']['id'],second['payload']['paper']['id'])

    def test_invalid_uploaded_pdf_does_not_create_paper(self):
        result=self.upload(b'not a pdf');self.assertEqual(result['status'],400)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)


if __name__=='__main__': unittest.main()
