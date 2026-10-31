"""Corrections retain exercise identity, material versions and student evidence."""
import copy,json,unittest,uuid
from pathlib import Path
from unittest.mock import patch

import test_prepared_practice as prepared
from app.learning.tasks import create_task,deliver,finish_task,receipt,digest,retry_task
from app.learning.practice_review import normalize_request,validate_math_delimiters
from app.learning.loop import submit_probe
from app.learning.workflows import enqueue
from app.learning.contracts import result_schema


class PracticeReviewTests(unittest.TestCase):
    def setUp(self):
        self.p=prepared.PreparedPracticeTests();self.p.setUp()
        self.p.start();self.p.read()
        saved=deliver(self.p.conn,self.p.f.root,self.p.data,self.p.payload(),self.p.f.lease)
        finish_task(self.p.conn,self.p.f.task['id']);self.p.conn.commit()
        self.conn=self.p.conn
        self.probe=self.conn.execute('SELECT * FROM diagnostic_probes WHERE paper_id=? ORDER BY rowid DESC',('paper-test',)).fetchone()
        self.pid=self.probe['id'];self.session='prepared-session'

    def tearDown(self):self.p.tearDown()

    def request(self,pids=None,fields=None):
        values=[]
        for pid in pids or [self.pid]:
            row=self.conn.execute('SELECT payload_json FROM diagnostic_probes WHERE id=?',(pid,)).fetchone()
            values.append({'probe_id':pid,'payload_revision':digest(json.loads(row[0])),
                           'allowed_fields':fields or ['expected','solution_note']})
        return {'probes':values,'note':'核对最终解答，不修改学生作答。'}

    def start(self,request=None):
        self.task=create_task(self.conn,self.p.f.root,self.p.data,'review_practice','paper-test',self.session,
                              str(uuid.uuid4()),review_request=request or self.request())
        self.lease=self.p.bind(self.task,self.session)
        return self.task

    def read(self,task=None,lease=None):
        task=task or self.task;lease=lease or self.lease
        scope=json.loads(task['input_json'])['practice_review']
        for entry in scope['entries']:
            self.p.tool('task_context',{'probe_ids':[entry['probe']['id']]},lease)
            self.p.tool('read_bank',{'bank_id':entry['probe']['bank_id'],'probe_id':entry['probe']['id'],'role':'all'},lease)
            self.p.tool('task_context',{'topic_ids':entry['topic_ids']},lease)

    def payload(self):
        scope=json.loads(self.task['input_json'])['practice_review'];values=[]
        for entry in scope['entries']:
            old=json.loads(entry['probe']['payload_json'])
            values.append({'probe_id':entry['probe']['id'],'payload_revision':entry['request']['payload_revision'],
                'status':'corrected','expected':old['expected'],'solution_note':'$f\u2032(x)=2x\\cos(x^2)$，已保留内层导数。',
                'reason':'把逐层导数展开写清楚。','checks':[{'claim':'链式法则','calculation':'外层cos(x²)乘内层2x。','conclusion':'保留内层因子。'}],
                'limitations':[]})
        return {'schema_version':'2.1','kind':'review_practice','paper_id':'paper-test','task_id':self.task['id'],
                'input_revision':self.task['input_revision'],'author':'isolated-review','result':{'summary':'仅修解答。','revisions':values}}

    def save(self,value=None):return deliver(self.conn,self.p.f.root,self.p.data,value or self.payload(),self.lease)

    def test_corrects_only_authorized_fields_and_retains_binding_and_old_history(self):
        before=dict(self.probe);binding=[tuple(r) for r in self.conn.execute('SELECT * FROM practice_question_bindings')]
        self.start();self.read();saved=self.save()
        after=dict(self.conn.execute('SELECT * FROM diagnostic_probes WHERE id=?',(self.pid,)).fetchone())
        self.assertEqual({k:v for k,v in before.items() if k!='payload_json'},{k:v for k,v in after.items() if k!='payload_json'})
        original=json.loads(before['payload_json']);updated=json.loads(after['payload_json'])
        self.assertEqual({k:v for k,v in original.items() if k!='solution_note'},{k:v for k,v in updated.items() if k!='solution_note'})
        self.assertEqual(binding,[tuple(r) for r in self.conn.execute('SELECT * FROM practice_question_bindings')])
        history=json.loads(self.conn.execute("SELECT payload FROM record_versions WHERE kind='probe' AND record_id=?",(self.pid,)).fetchone()[0])
        self.assertEqual(history,before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_solution_revisions WHERE result_id=?',(saved['result_id'],)).fetchone()[0],1)

    def test_repeated_delivery_and_saved_task_retry_are_idempotent(self):
        self.start();self.read();value=self.payload();first=self.save(value);second=self.save(value)
        self.assertTrue(second['reused']);self.assertEqual(first['result_id'],second['result_id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_solution_revisions').fetchone()[0],1)
        retry=retry_task(self.conn,self.p.f.root,self.p.data,self.task['id'])
        lease=self.p.bind(retry,self.session)
        again=deliver(self.conn,self.p.f.root,self.p.data,value,lease)
        self.assertTrue(again['reused'])

    def test_unread_frozen_assignment_cannot_be_saved(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.save()
        self.assertIsNone(receipt(self.conn,self.task['id']))

    def test_forbidden_field_or_missing_or_extra_probe_is_rejected(self):
        self.start();self.read();value=self.payload();value['result']['revisions'][0]['prompt']='different task'
        with self.assertRaisesRegex(ValueError,'结构'):self.save(value)
        value=self.payload();value['result']['revisions'][0]['probe_id']='other-probe'
        with self.assertRaisesRegex(ValueError,'指定练习'):self.save(value)
        self.assertIsNone(receipt(self.conn,self.task['id']))

    def test_expected_cannot_change_when_only_solution_note_is_authorized(self):
        self.start(self.request(fields=['solution_note']));self.read();value=self.payload()
        value['result']['revisions'][0]['expected']='a different result'
        with self.assertRaisesRegex(ValueError,'未授权'):self.save(value)

    def test_unchanged_and_needs_material_cannot_change_original_solution(self):
        self.start();self.read();value=self.payload();value['result']['revisions'][0]['status']='unchanged'
        with self.assertRaisesRegex(ValueError,'保留原解答'):self.save(value)
        value['result']['revisions'][0]['status']='needs_material'
        with self.assertRaisesRegex(ValueError,'保留原解答'):self.save(value)

    def test_needs_material_preserves_payload_and_does_not_create_attempt_or_event(self):
        self.start();self.read();value=self.payload();item=value['result']['revisions'][0]
        old=json.loads(self.probe['payload_json']);item.update(status='needs_material',expected=old['expected'],
            solution_note=old['solution_note'],checks=[],limitations=['需要核对原图的一个符号。'])
        before=self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0]
        self.save(value)
        self.assertEqual(self.conn.execute('SELECT payload_json FROM diagnostic_probes WHERE id=?',(self.pid,)).fetchone()[0],self.probe['payload_json'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)

    def test_existing_student_attempt_and_feedback_are_not_rewritten(self):
        submit_probe(self.conn,self.pid,{'response':'本人原步骤。','request_id':str(uuid.uuid4())})
        before=[tuple(r) for r in self.conn.execute('SELECT * FROM probe_attempts')]
        events=[tuple(r) for r in self.conn.execute('SELECT * FROM learning_events')]
        self.start();self.read();self.save()
        self.assertEqual(before,[tuple(r) for r in self.conn.execute('SELECT * FROM probe_attempts')])
        self.assertEqual(events,[tuple(r) for r in self.conn.execute('SELECT * FROM learning_events')])

    def test_stale_payload_is_rejected_and_new_student_work_invalidates_task(self):
        request=self.request();request['probes'][0]['payload_revision']='f'*64
        with self.assertRaisesRegex(ValueError,'解答版本'):self.start(request)
        self.start();self.read();submit_probe(self.conn,self.pid,{'response':'new work','request_id':str(uuid.uuid4())})
        with self.assertRaisesRegex(ValueError,'作答或固定材料'):self.save()

    def test_live_bank_update_does_not_replace_frozen_materials(self):
        self.start();self.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('new unrelated answer',prepared.BANK))
        self.conn.commit();self.read();self.save()

    def test_missing_read_or_corrupted_material_rejects_changes(self):
        self.start();self.read()
        inputs=json.loads(self.task['input_json']);entry=inputs['practice_review']['entries'][0]
        from app.storage.practice_materials import image_path
        image_path(self.p.data,entry['binding'],'question').write_bytes(b'broken')
        with self.assertRaisesRegex(ValueError,'固定材料'):self.save()
        self.assertIsNone(receipt(self.conn,self.task['id']))

    def test_scope_validation_contract_and_queue_do_not_merge_distinct_authorizations(self):
        bad=self.request();bad['probes'][0]['allowed_fields']=['prompt']
        with self.assertRaises(ValueError):normalize_request(bad)
        with self.assertRaises(ValueError):result_schema('review_practice','1.9')
        with self.assertRaises(ValueError):result_schema('prepare_practice','2.1')
        first=enqueue(self.conn,self.p.f.root,self.p.data,'review_practice','paper-test',str(uuid.uuid4()),review_request=self.request())
        second=enqueue(self.conn,self.p.f.root,self.p.data,'review_practice','paper-test',str(uuid.uuid4()),review_request=self.request(fields=['solution_note']))
        self.assertNotEqual(first['id'],second['id'])

    def test_same_request_cannot_change_note_or_scope(self):
        self.start();request=self.request();request['note']='different scope'
        with self.assertRaisesRegex(ValueError,'不能更换'):
            create_task(self.conn,self.p.f.root,self.p.data,'review_practice','paper-test',self.session,self.task['request_id'],review_request=request)

    def test_unsaved_retry_keeps_scope_and_rejects_stale_definition(self):
        self.start();inputs=self.task['input_json']
        retried=retry_task(self.conn,self.p.f.root,self.p.data,self.task['id'])
        self.assertEqual(retried['input_json'],inputs)
        with patch('app.learning.practice_review.mapping_versions.dependencies',return_value={'changed':'definition'}):
            with self.assertRaisesRegex(ValueError,'定义或层级'):
                retry_task(self.conn,self.p.f.root,self.p.data,self.task['id'])

    def test_api_controller_selects_new_contract_without_auto_selecting_more_questions(self):
        from types import SimpleNamespace
        from app.agent.controller import AgentController
        calls=[]
        runtime=SimpleNamespace(bridge=SimpleNamespace(queue_task=lambda *args,**kwargs:calls.append((args,kwargs)) or {'queued':True}))
        body={'kind':'review_practice','paper_id':'paper-test','request_id':str(uuid.uuid4()),'review_request':self.request()}
        result=AgentController(runtime).invoke('task',body)
        self.assertTrue(result['queued']);self.assertEqual(calls[0][1]['contract_version'],'2.1')
        self.assertTrue(calls[0][1]['index_after']);self.assertFalse(calls[0][1]['auto_prepare'])

    def test_archived_foreign_or_retired_records_cannot_be_corrected(self):
        request=self.request();request['probes'][0]['probe_id']='other-paper-probe'
        with self.assertRaisesRegex(ValueError,'不存在'):self.start(request)
        self.conn.execute('INSERT INTO retired_probes VALUES(?,?,?)',(self.pid,'fixture retired','now'))
        with self.assertRaisesRegex(ValueError,'停用'):self.start()

    def test_review_task_cannot_read_student_attempt_or_search_for_extra_exercises(self):
        self.start()
        for action,payload in [('catalog',{}),('read_attempt',{'attempt_id':'not-a-real-attempt'})]:
            with self.assertRaisesRegex(ValueError,'不操作学生作答'):self.p.tool(action,payload,self.lease)

    def test_delimiter_guard_reports_broken_math_without_guessing_symbols(self):
        for text in ('$x','$$x$','\\(x','\\[x\\)'):
            with self.assertRaises(ValueError):validate_math_delimiters(text,'expected')
        for text in ('$x$。','$$x$$','\\(x\\)','\\[x\\]','费用\\$20'):
            validate_math_delimiters(text,'expected')
        self.start();self.read();value=self.payload();value['result']['revisions'][0]['expected']='$unclosed'
        with self.assertRaisesRegex(ValueError,'未闭合'):self.save(value)

    def test_second_revision_failure_rolls_back_first_and_all_receipts(self):
        clone='probe-isolated-second';row=dict(self.probe)
        self.conn.execute('INSERT INTO diagnostic_probes VALUES(?,?,?,?,?,?,?,?)',
            (clone,row['paper_id'],row['question_id'],row['bank_id'],row['skill_id'],row['payload_json'],row['status'],row['created_at']))
        binding=self.conn.execute('SELECT * FROM practice_question_bindings WHERE probe_id=?',(self.pid,)).fetchone()
        self.conn.execute('INSERT INTO practice_question_bindings VALUES(?,?,?,?,?,?,?)',
            (binding['result_id'],clone,binding['bank_id'],binding['annotation_id'],binding['content_revision'],binding['material_revision'],binding['payload_json']))
        self.conn.commit();self.start(self.request([self.pid,clone],fields=['solution_note']));self.read()
        value=self.payload();value['result']['revisions'][-1]['expected']='not authorized'
        before=[tuple(r) for r in self.conn.execute('SELECT * FROM diagnostic_probes ORDER BY id')]
        with self.assertRaisesRegex(ValueError,'未授权'):self.save(value)
        self.assertEqual(before,[tuple(r) for r in self.conn.execute('SELECT * FROM diagnostic_probes ORDER BY id')])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_solution_revisions').fetchone()[0],0)
        self.assertIsNone(receipt(self.conn,self.task['id']))


if __name__=='__main__':unittest.main()
