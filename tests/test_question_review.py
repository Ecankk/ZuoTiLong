import copy
from io import BytesIO
import json
import time
import unittest
import uuid
from unittest.mock import patch

from PIL import Image
import database_fixture as server
import test_learning_tasks as fixtures
from app.storage.images import save_answer_image
from app.learning.loop import loop_snapshot
from app.learning.tasks import create_task, bind_turn, deliver, finish_task, task_record, retry_task
from app.agent.tools import execute
from app.storage.maintenance import cleanup_images
from app.learning.question_review import scoped_indexes
from app.learning.workflows import enqueue, guard, reconcile, listing


class QuestionReviewTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.LearningTaskTests();self.base.setUp()
        self.conn=self.base.conn;self.root=self.base.root;self.data=self.base.data
        self.base.start();self.base.read_page()
        payload=self.base.analysis();report=payload['result']['report']
        q=report['questions'][0]
        q.update(correctness='unknown',first_error=None,skill_events=[])
        q['answer_evidence'].update(student_state='unreadable',student_work='',marking='unclear',marking_note='overlapping marks')
        issue='第1题原作答需要局部复核'
        report.update(review={'status':'needs_review','issues':[issue]},limitations=[issue])
        payload['result']['completion']='partial'
        saved=deliver(self.conn,self.root,self.data,payload,self.base.lease)
        finish_task(self.conn,self.base.task['id']);self.conn.commit()
        self.report_id=saved['projection']['report_id']
        self.request={'question_id':self.conn.execute("SELECT id FROM questions WHERE number='1'").fetchone()[0],
                      'report_id':self.report_id,'note':'','image_ids':[],'image_roles':{}}

    def tearDown(self):
        self.base.tearDown()

    def start(self,request=None):
        self.base.start('review_question',review_request=request or self.request)
        self.task=self.base.task
        return self.task

    def read(self):
        self.conn.commit()
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            return execute(self.root,self.data,'read_paper',{'paper_id':'paper-test',
                           'question_id':self.request['question_id']},lease=self.base.lease)

    def result(self):
        scope=json.loads(self.task['input_json'])['question_review']
        q=copy.deepcopy(scope['question'])
        q.update(correctness='wrong',observation='The original answer differs from the verified answer.')
        q['answer_evidence'].update(student_state='visible',student_work='original answer',
                                    marking='wrong',marking_note='a separate later correction')
        q['skill_events']=[{'skill_id':'bounds','label':'bounds','kind':'exam_error'}]
        return self.base.envelope({'question':q,'review':{'status':'verified','issues':[]},
            'completion':'complete','summary':'Scoped review saved; other observations preserved.',
            'priorities':[],
            'resolved_issue_indexes':[0],'resolved_limitation_indexes':[0]})

    def save(self,payload=None):
        return deliver(self.conn,self.root,self.data,payload or self.result(),self.base.lease)

    def test_review_without_note_or_photo_reads_page_and_crop_and_preserves_other_evidence(self):
        untouched=dict(self.conn.execute("SELECT * FROM questions WHERE number='2'").fetchone())
        events=[tuple(r) for r in self.conn.execute('SELECT * FROM learning_events WHERE question_id=?',(untouched['id'],))]
        diagnosis=tuple(self.conn.execute('SELECT * FROM question_diagnoses WHERE question_id=?',(untouched['id'],)).fetchone())
        self.start();content=self.read()
        self.assertEqual(sum(c['type']=='image' for c in content),2)
        saved=self.save();again=self.save()
        self.assertTrue(again['reused']);self.assertEqual(saved['result_id'],again['result_id'])
        self.assertEqual(dict(self.conn.execute('SELECT * FROM questions WHERE id=?',(untouched['id'],)).fetchone()),untouched)
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM learning_events WHERE question_id=?',(untouched['id'],))],events)
        self.assertEqual(tuple(self.conn.execute('SELECT * FROM question_diagnoses WHERE question_id=?',(untouched['id'],)).fetchone()),diagnosis)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)
        self.assertFalse(loop_snapshot(self.conn)['reports'][0]['needs_verification'])
        from app.learning.legacy_profile import build_profile
        self.assertEqual(build_profile(self.conn)[0]['failures'],2)

    def test_material_read_scope_and_target_are_enforced(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.save()
        self.read();bad=self.result();bad['result']['question']['number']=2
        with self.assertRaisesRegex(ValueError,'指定题号'):self.save(bad)
        with self.assertRaisesRegex(ValueError,'其他题'):
            with patch('app.agent.tools.connection',lambda data:server.connect()):
                execute(self.root,self.data,'read_paper',{'paper_id':'paper-test','question_id':'another'},lease=self.base.lease)

    def test_photo_and_note_survive_queue_and_cleanup_without_becoming_attempt(self):
        raw=BytesIO();Image.new('RGB',(100,80),'white').save(raw,format='PNG')
        image=save_answer_image(self.conn,self.data,raw.getvalue())
        request={**self.request,'note':'Please re-read the original mark.',
                 'image_ids':[image['id']],'image_roles':{image['id']:'own_work'}}
        request_id=str(uuid.uuid4())
        job=enqueue(self.conn,self.root,self.data,'review_question','paper-test',request_id,
                    review_request=request,auto_prepare=True)
        duplicate=enqueue(self.conn,self.root,self.data,'review_question','paper-test',str(uuid.uuid4()),
                          review_request=request,auto_prepare=True)
        self.assertEqual(job['id'],duplicate['id'])
        self.assertEqual(json.loads(job['review_json'])['note'],request['note'])
        self.conn.commit();self.start(request);content=self.read()
        self.assertEqual(sum(c['type']=='image' for c in content),3)
        self.save();self.conn.commit()
        self.assertEqual(cleanup_images(self.conn,self.data,min_age=0)['moved'],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)
        self.assertEqual(loop_snapshot(self.conn)['question_reviews'][0]['image_ids'],[image['id']])

    def test_old_parent_modified_question_and_pdf_cannot_overwrite(self):
        for mutation,error in (
            (lambda:self.conn.execute("UPDATE questions SET notes='changed' WHERE number='1'"),'材料已变化'),
            (lambda:self.conn.execute("UPDATE agent_reports SET created_at='later' WHERE id=?",(self.report_id,)),'材料已变化')):
            self.start();self.read();self.conn.commit()
            mutation()
            with self.assertRaisesRegex(ValueError,error):self.save()
            self.conn.rollback()
            self.conn.execute("UPDATE learning_tasks SET status='abandoned' WHERE id=?",(self.task['id'],));self.conn.commit()
        self.start();self.read()
        self.base.fixture.pdf.write_bytes(self.base.fixture.pdf.read_bytes()+b'\n')
        with self.assertRaisesRegex(ValueError,'原PDF已改变'):self.save()

    def test_other_issue_cannot_be_cleared_or_silently_passed(self):
        row=self.conn.execute('SELECT report_json FROM agent_reports WHERE id=?',(self.report_id,)).fetchone()
        report=json.loads(row[0]);report['review']['issues'].append('第2题条件仍需核对')
        self.conn.execute('UPDATE agent_reports SET report_json=? WHERE id=?',(json.dumps(report),self.report_id));self.conn.commit()
        self.start();self.read();payload=self.result()
        with self.assertRaisesRegex(ValueError,'仍需核对'):self.save(payload)
        payload['result']['resolved_issue_indexes']=[0,1]
        with self.assertRaisesRegex(ValueError,'其他题'):self.save(payload)
        payload['result'].update(resolved_issue_indexes=[0],completion='partial')
        self.save(payload)
        report=loop_snapshot(self.conn)['reports'][0]
        self.assertTrue(report['needs_verification']);self.assertIn('第2题条件仍需核对',report['review']['issues'])

    def test_still_uncertain_saves_a_recoverable_review_without_practice(self):
        self.start();self.read();payload=self.result()
        payload['result'].update(question=json.loads(self.task['input_json'])['question_review']['question'],
            completion='needs_material',review={'status':'needs_review','issues':['第1题请补拍选项左侧区域']})
        self.save(payload);finish_task(self.conn,self.task['id'])
        self.assertTrue(loop_snapshot(self.conn)['reports'][0]['needs_verification'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],0)

    def test_confirmed_blank_or_unknown_score_does_not_make_verified_analysis_partial(self):
        self.start();self.read();payload=self.result()
        payload['result']['completion']='partial'
        with self.assertRaisesRegex(ValueError,'学生是否全部答对或做完'):self.save(payload)
        payload['result']['completion']='complete';self.save(payload)
        self.assertFalse(loop_snapshot(self.conn)['reports'][0]['needs_verification'])

    def test_scoped_text_indexes_never_clear_shared_or_global_issues(self):
        self.assertEqual(scoped_indexes(['第1题模糊','第1题及第2题模糊','整卷分数未知','Q1 unclear'],1),[0,3])

    def test_parent_change_blocks_old_queue_and_idempotency_cannot_swap_material(self):
        rid=str(uuid.uuid4())
        job=enqueue(self.conn,self.root,self.data,'review_question','paper-test',rid,review_request=self.request)
        with self.assertRaisesRegex(ValueError,'更换材料'):
            enqueue(self.conn,self.root,self.data,'review_question','paper-test',rid,review_request={**self.request,'note':'changed'})
        self.base.fixture.apply()
        with self.assertRaisesRegex(ValueError,'分析版本已变化'):
            guard(self.conn,self.root,self.data,'review_question','paper-test',review_request=json.loads(job['review_json']))

    def test_retry_saved_review_keeps_authoritative_receipt_and_original_task(self):
        self.start();self.read();saved=self.save();self.conn.commit()
        renewed=retry_task(self.conn,self.root,self.data,self.task['id'])
        self.assertEqual(renewed['result_id'],saved['result_id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM agent_reports').fetchone()[0],2)

    def test_queue_chains_after_local_delivery_and_does_not_duplicate(self):
        job=enqueue(self.conn,self.root,self.data,'review_question','paper-test',str(uuid.uuid4()),
                    review_request=self.request,auto_prepare=True)
        self.task=create_task(self.conn,self.root,self.data,'review_question','paper-test','session-test',job['request_id'],
                              review_request=self.request,workflow_id=job['workflow_id'])
        self.base.task=self.task;self.base.kind='review_question'
        bind_turn(self.conn,self.task['id'],'session-test',self.task['run_token'],'turn-review')
        self.base.lease={'task_id':self.task['id'],'session_id':'session-test','run_token':self.task['run_token'],'turn_id':'turn-review'}
        self.read();self.save();reconcile(self.conn,self.root,self.data)
        self.assertEqual(len(listing(self.conn)),2)
        finish_task(self.conn,self.task['id']);reconcile(self.conn,self.root,self.data);reconcile(self.conn,self.root,self.data)
        self.assertEqual(sum(j['kind']=='prepare_practice' for j in listing(self.conn)),1)
