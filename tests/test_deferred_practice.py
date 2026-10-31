from app.storage.boundaries import library_root
"""Unproved old material stays readable as history without blocking new plans."""
import json,unittest,uuid
from types import SimpleNamespace
from PIL import Image
import test_legacy_practice_upgrade as legacy
import test_question_annotations as annotation_fixtures
from app.learning.tasks import deliver,finish_task,task_package,create_task
from app.learning.plans import practice_state
from app.learning.loop import loop_snapshot,submit_probe,supplement_attempt
from app.learning.workflows import enqueue
from app.bank.access import init_access
from app.bank import annotations


class DeferredPracticeTests(unittest.TestCase):
    def setUp(self):
        self.base=legacy.LegacyPracticeUpgradeTests();self.base.setUp();self.addCleanup(self.base.doCleanups)
        self.f=self.base.f;self.case=self.base.case;self.conn=self.base.conn;self.data=self.base.data
        self.pid=self.base.pid

    def remove_proof(self):
        self.conn.execute("DELETE FROM task_reads WHERE task_id=? AND kind='bank' AND role='question'",(self.base.origin,))

    def save_without_unsafe_old_exercise(self):
        self.base.start();self.case.tool('task_context',{'topic_ids':[legacy.TOPIC]})
        value=self.base.value();value['result']['retained_exercises']=[]
        value['result']['goals'][0].update(decision='monitor',reason='旧题原版本未核，保留历史；本轮不强行增加练习。')
        saved=deliver(self.conn,self.f.root,self.data,value,self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit();return saved

    def test_missing_proof_does_not_force_a_fabricated_retained_exercise(self):
        self.remove_proof();self.save_without_unsafe_old_exercise()
        package=task_package(self.conn,self.f.task['id'])
        self.assertNotIn(self.pid,package['required_retained_probe_ids'])
        state=practice_state(self.conn,'paper-test')
        self.assertTrue(state['is_current']);self.assertEqual(state['probe_ids'],[])
        self.assertIn(self.pid,[p['probe_id'] for p in state['deferred_probes']])
        self.base.unchanged()

    def test_history_is_preserved_but_the_current_bank_image_is_not_substituted(self):
        self.remove_proof();self.save_without_unsafe_old_exercise()
        item=next(p for p in loop_snapshot(self.conn)['probes'] if p['id']==self.pid)
        self.assertTrue(item['review_reason']);self.assertFalse(item['is_current'])
        for field in ('question_image','question_text','analysis_image','expected','solution_note','prompt'):
            self.assertNotIn(field,item)
        self.assertEqual(item['attempts'][0]['response'],self.base.original['response'])
        from http_support import client
        with client() as http:
            old=http.get('/api/bank/'+legacy.BANK+'/question',params={'probe_id':self.pid})
            self.assertEqual(old.status_code,409)
            library=http.get('/api/bank/'+legacy.BANK+'/question',params={'view':'library'})
            self.assertEqual(library.status_code,200)
        self.base.unchanged()

    def test_waiting_history_cannot_receive_new_submissions_supplements_or_grade_tasks(self):
        self.remove_proof();self.save_without_unsafe_old_exercise()
        calls=[lambda:submit_probe(self.conn,self.pid,{'response':'new response'}),
            lambda:supplement_attempt(self.conn,self.base.attempt,{'response':'new steps'}),
            lambda:enqueue(self.conn,self.f.root,self.data,'grade_attempt','paper-test',str(uuid.uuid4()),self.base.attempt),
            lambda:create_task(self.conn,self.f.root,self.data,'grade_attempt','paper-test','test',str(uuid.uuid4()),attempt_id=self.base.attempt)]
        for call in calls:
            with self.assertRaisesRegex(ValueError,'原题版本待核'):call()
        self.base.unchanged()

    def test_waiting_record_survives_another_empty_plan_without_duplication(self):
        self.remove_proof();self.save_without_unsafe_old_exercise();self.save_without_unsafe_old_exercise()
        state=practice_state(self.conn,'paper-test')
        self.assertEqual([p['probe_id'] for p in state['deferred_probes']].count(self.pid),1)
        self.base.unchanged()

    def test_changed_old_image_can_be_kept_as_history_without_changing_student_evidence(self):
        Image.new('RGB',(40,40),'orange').save(library_root(self.data)/'bank-assets/question.png')
        self.save_without_unsafe_old_exercise()
        item=next(p for p in practice_state(self.conn,'paper-test')['deferred_probes'] if p['probe_id']==self.pid)
        self.assertIn('不一致',item['reason']);self.base.unchanged()

    def test_other_ready_questions_can_be_assigned_while_the_unproved_record_waits(self):
        self.remove_proof();bank='math3-2020-02'
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at) VALUES(?,?,?,?,?,'now')",
            (bank,'isolated-text','求 f(x)=ln(1+x²) 的导数。','2x/(1+x²)','ln的导数乘以1+x²的导数。'))
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',(bank,'{}','',None,None));init_access(self.conn)
        task=create_task(self.conn,self.f.root,self.data,'annotate_questions',None,'test-preparation',str(uuid.uuid4()),task_scope={'bank_ids':[bank]})
        lease=self.case.bind(task,'test-preparation')
        self.case.tool('read_bank',{'bank_id':bank,'role':'all'},lease)
        self.case.tool('task_context',{'topic_ids':[legacy.TOPIC]},lease)
        result=annotation_fixtures.QuestionPreparationTests.annotation_result(SimpleNamespace(task=task))
        question=result['questions'][0]
        question.update(reference_reasoning='1+x²>0。令u=1+x²，则df/dx=(1/u)·2x=2x/(1+x²)。',
            fingerprint={'conditions':['f(x)=ln(1+x²)'],'goal':'求一阶导数','methods':['链式求导'],'operations':['逐层求导并相乘']})
        question['bindings'][0]['evidence']='外层为ln，内层为1+x²。'
        deliver(self.conn,self.f.root,self.data,{'schema_version':'1.7','task_id':task['id'],'kind':task['kind'],
            'paper_id':None,'input_revision':task['input_revision'],'author':'isolated-preparation','result':result},lease)
        finish_task(self.conn,task['id']);self.conn.commit()
        annotation=annotations.current(self.conn,self.data,bank)
        self.base.start();self.case.tool('task_context',{'topic_ids':[legacy.TOPIC]})
        catalog=self.case.tool('catalog',{'topic_ids':[legacy.TOPIC]})
        self.assertFalse(next(p for p in catalog['existing_exercises'] if p['probe_id']==self.pid)['can_reuse'])
        self.case.tool('read_bank',{'bank_id':bank,'role':'all'})
        value=self.case.payload();value['result']['retained_exercises']=[]
        value['result']['exercises'][0].update(bank_id=bank,annotation_id=annotation['id'],
            expected='2x/(1+x²)',solution_note='外层ln求导再乘内层导数。')
        deliver(self.conn,self.f.root,self.data,value,self.f.lease);finish_task(self.conn,self.f.task['id']);self.conn.commit()
        state=practice_state(self.conn,'paper-test')
        self.assertEqual(len(state['probe_ids']),1);self.assertNotIn(self.pid,state['probe_ids'])
        self.assertIn(self.pid,[p['probe_id'] for p in state['deferred_probes']])
        self.assertEqual(dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(self.base.attempt,)).fetchone()),self.base.original)
