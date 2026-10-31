from app.learning.tasks import finish_task
import copy
import json
import unittest
import uuid
from unittest.mock import patch

from app.bank import annotations
from app.knowledge import preparation
from app.learning.tasks import bind_turn, finish_task, retry_task


class AnnotationReferenceVersionTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn,self.data,self.root=self.f.conn,self.f.data,self.f.root
        self.f.prepare_catalog();self.ids=self.f.seed_questions(aliases=True)

    def change_second_reference(self):
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?',('错误参考：sin(x²)的导数为0。',self.ids[1]));self.conn.commit()

    def save_first(self,legacy=False):
        if legacy:
            with patch.object(annotations,'RULE_REVISION','mathlens.question-topics/v1'):
                self.f.start('annotate_questions',{'bank_ids':[self.ids[0]]})
        else:self.f.start('annotate_questions',{'bank_ids':[self.ids[0]]})
        self.f.read_annotation_material()
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()

    def test_same_question_with_different_references_is_not_silently_verified(self):
        self.change_second_reference();self.save_first()
        self.assertIsNotNone(annotations.current(self.conn,self.data,self.ids[0]))
        self.assertIsNone(annotations.current(self.conn,self.data,self.ids[1]))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotation_links WHERE bank_id=?',(self.ids[1],)).fetchone()[0],0)
        inputs=annotations.capture(self.conn,self.data,{'bank_ids':self.ids})
        self.assertEqual(len(inputs['bank_questions']),2)
        self.assertEqual(len({q['entity_id'] for q in inputs['bank_questions']}),1)

    def test_legacy_source_stays_valid_but_its_other_reference_version_does_not(self):
        self.change_second_reference();self.save_first(legacy=True)
        before=[tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')]
        a=annotations.current(self.conn,self.data,self.ids[0])
        self.assertEqual(a['rule_revision'],'mathlens.question-topics/v1')
        self.assertIsNone(annotations.current(self.conn,self.data,self.ids[1]))
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')],before)

    def test_reusable_mathematics_is_a_draft_and_new_reference_conflict_is_separate(self):
        self.change_second_reference();self.save_first(legacy=True)
        self.f.start('annotate_questions',{'bank_ids':[self.ids[1]]})
        source=json.loads(self.f.task['input_json'])['bank_questions'][0]
        draft=source['reusable_analysis']
        self.assertEqual(draft['source_bank_id'],self.ids[0])
        self.assertIn('reference_reasoning',draft)
        self.assertNotIn('answer_check',draft);self.assertNotIn('status',draft)
        context=self.f.tool('task_context',{'bank_ids':[self.ids[1]]})
        self.assertEqual(context['questions'][0]['reusable_analysis'],draft)
        self.assertNotIn('materials',context['questions'][0])
        value=self.f.annotation_result();value['questions'][0].update(status='needs_review',
            answer_check={'status':'conflict','note':'本版本参考写0，与独立导数计算冲突。'},limitations=['本版本解析需核对。'])
        self.f.read_annotation_material();self.f.tool('apply_report',{'result':self.f.envelope(value)})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.assertEqual(annotations.current(self.conn,self.data,self.ids[1])['analysis']['status'],'needs_review')
        self.assertEqual(annotations.current(self.conn,self.data,self.ids[0])['analysis']['status'],'ready')
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],0)

    def test_different_source_labels_with_identical_references_can_reuse(self):
        self.conn.execute('UPDATE bank_questions SET stem=? WHERE id=?',('另一份已确认同题的卷面出处：求sin(x²)导数。',self.ids[1]));self.conn.commit()
        self.save_first()
        a=annotations.current(self.conn,self.data,self.ids[0]);b=annotations.current(self.conn,self.data,self.ids[1])
        self.assertEqual(a['id'],b['id'])
        self.assertEqual(len(annotations.capture(self.conn,self.data,{'bank_ids':self.ids})['bank_questions']),1)

    def test_old_unsaved_task_retry_and_delivery_use_its_captured_rule(self):
        self.change_second_reference()
        with patch.object(annotations,'RULE_REVISION','mathlens.question-topics/v1'):
            self.f.start('annotate_questions',{'bank_ids':self.ids})
        original=self.f.task['input_revision']
        task=retry_task(self.conn,self.root,self.data,self.f.task['id'])
        self.assertEqual(task['input_revision'],original)
        bind_turn(self.conn,task['id'],'same-session',task['run_token'],'legacy-retry');self.conn.commit()
        self.f.task=task;self.f.lease.update(run_token=task['run_token'],turn_id='legacy-retry')
        self.f.read_annotation_material();self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.assertIsNotNone(annotations.current(self.conn,self.data,self.ids[0]))
        self.assertIsNone(annotations.current(self.conn,self.data,self.ids[1]))

    def test_resume_rechecks_previously_reused_completed_records(self):
        self.change_second_reference();self.save_first(legacy=True)
        run=preparation.start(self.conn,self.root,self.data,kind='questions',request_id=str(uuid.uuid4()),item_ids=self.ids)
        rid=run['runs'][0]['id'];preparation.action(self.conn,self.root,self.data,rid,'pause')
        # Simulate the saved item status of the old, overly broad reuse gate.
        self.conn.execute("UPDATE knowledge_preparation_items SET status='completed',job_id=NULL WHERE run_id=?",(rid,))
        result=preparation.action(self.conn,self.root,self.data,rid,'resume')
        self.assertEqual(result['runs'][0]['counts'],{'completed':1,'running':1})
        row=self.conn.execute("SELECT scope_json FROM workflow_jobs WHERE workflow_id=? AND status='queued' ORDER BY rowid DESC LIMIT 1",(rid,)).fetchone()
        self.assertEqual(json.loads(row[0])['bank_ids'],[self.ids[1]])


if __name__=='__main__':unittest.main()
