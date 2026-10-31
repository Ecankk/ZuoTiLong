from app.learning.tasks import finish_task
import json
import unittest
from unittest.mock import patch

from app.bank import annotations
from app.knowledge import catalog
from app.learning.tasks import bind_turn, finish_task, receipt, retry_task


class DefinitionReviewDraftTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn,self.data,self.root=self.f.conn,self.f.data,self.f.root
        self.f.prepare_catalog();self.ids=self.f.seed_questions(aliases=True)

    def save_original(self,rule=None,status='ready'):
        with patch.object(annotations,'RULE_REVISION',rule or annotations.RULE_REVISION):
            self.f.start('annotate_questions',{'bank_ids':[self.ids[0]]})
        self.f.read_annotation_material()
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result(status))})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        return self.conn.execute('SELECT id FROM question_annotations ORDER BY rowid DESC').fetchone()[0]

    def change_catalogue(self,operation=None):
        value=catalog.base_document(self.conn)
        node=next(n for n in value['nodes'] if n['id']=='GS-04-001')
        if operation:operation(value,node)
        else:node['conditions'].append('复核所用函数在开区间上满足相应可导条件。')
        parent=catalog.active_id(self.conn);draft=catalog.create_draft(self.conn,value,expected_parent=parent)
        catalog.publish(self.conn,draft['id'],expected_parent=parent,reviewer='isolated-revision-review')
        self.conn.commit()

    def captured(self,bid=None,rule=None):
        return annotations.capture(self.conn,self.data,{'bank_ids':[bid or self.ids[0]]},rule_revision=rule)

    def test_changed_definition_provides_old_and_new_context_without_approval(self):
        aid=self.save_original();old=catalog.active_id(self.conn);self.change_catalogue()
        writes=self.conn.total_changes
        source=self.captured()['bank_questions'][0];draft=source['definition_review_draft']
        self.assertEqual(draft['annotation_id'],aid);self.assertEqual(draft['source_catalog_revision'],old)
        self.assertEqual(draft['review_catalog_revision'],catalog.active_id(self.conn))
        self.assertTrue(draft['review_required'])
        delta=next(x for x in draft['changed_knowledge'] if x['previous_id']=='GS-04-001')
        self.assertEqual(delta['changed_fields'],['conditions'])
        self.assertNotEqual(delta['previous']['conditions'],delta['current']['conditions'])
        self.assertIn('reference_reasoning',draft);self.assertIn('bindings',draft)
        self.assertNotIn('status',draft);self.assertNotIn('answer_check',draft)
        self.assertIsNone(annotations.current(self.conn,self.data,self.ids[0]))
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=['GS-04-001'])['total'],0)
        self.assertEqual(self.conn.total_changes,writes)

    def test_valid_analysis_and_pure_alias_edits_do_not_create_a_review_draft(self):
        self.save_original()
        self.assertNotIn('definition_review_draft',self.captured()['bank_questions'][0])
        self.change_catalogue(lambda value,node:node['aliases'].append('已核别名'))
        self.assertIsNotNone(annotations.current(self.conn,self.data,self.ids[0]))
        self.assertNotIn('definition_review_draft',self.captured()['bank_questions'][0])

    def test_changed_question_excludes_old_derivation(self):
        self.save_original();self.change_catalogue()
        self.conn.execute('UPDATE bank_questions SET stem=stem||? WHERE id=?',('且求二阶导数。',self.ids[0]));self.conn.commit()
        self.assertNotIn('definition_review_draft',self.captured()['bank_questions'][0])

    def test_changed_reference_excludes_old_derivation(self):
        self.save_original();self.change_catalogue()
        self.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('另一版本的错误参考。',self.ids[0]));self.conn.commit()
        self.assertNotIn('definition_review_draft',self.captured()['bank_questions'][0])

    def test_confirmed_alias_with_identical_references_keeps_the_same_historical_draft(self):
        aid=self.save_original();self.change_catalogue()
        draft=self.captured(self.ids[1])['bank_questions'][0]['definition_review_draft']
        self.assertEqual(draft['annotation_id'],aid)
        self.assertEqual(draft['source_bank_id'],self.ids[0])

    def test_confirmed_alias_with_different_reference_cannot_take_the_draft(self):
        self.save_original();self.change_catalogue()
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?',('不同版本，尚未经核对。',self.ids[1]));self.conn.commit()
        self.assertNotIn('definition_review_draft',self.captured(self.ids[1])['bank_questions'][0])

    def test_withdrawn_same_question_link_cannot_supply_a_historical_draft(self):
        self.save_original();self.change_catalogue()
        self.conn.execute('DELETE FROM bank_links');self.conn.commit()
        self.assertNotIn('definition_review_draft',self.captured(self.ids[1])['bank_questions'][0])
        self.assertIn('definition_review_draft',self.captured(self.ids[0])['bank_questions'][0])

    def test_draft_does_not_replace_current_material_or_definition_reading(self):
        old_id=self.save_original();self.change_catalogue()
        old_rows=[tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')]
        self.f.start('annotate_questions',{'bank_ids':[self.ids[0]]})
        inputs=json.loads(self.f.task['input_json']);self.assertIn('definition_review_draft',inputs['bank_questions'][0])
        reads=self.conn.execute('SELECT count(*) FROM task_reads WHERE task_id=?',(self.f.task['id'],)).fetchone()[0]
        context=self.f.tool('task_context',{'bank_ids':[self.ids[0]]})
        self.assertEqual(context['questions'][0]['definition_review_draft'],inputs['bank_questions'][0]['definition_review_draft'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM task_reads WHERE task_id=?',(self.f.task['id'],)).fetchone()[0],reads)
        value=self.f.envelope(self.f.annotation_result())
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.f.tool('apply_report',{'result':value})
        self.f.tool('read_bank',{'bank_id':self.ids[0],'role':'all'})
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.f.tool('apply_report',{'result':value})
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.f.tool('task_context',{'topic_ids':['GS-04-001']})
        result=self.f.tool('apply_report',{'result':value})
        self.assertEqual(self.f.tool('apply_report',{'result':value})['result_id'],result['result_id'])
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        current=annotations.current(self.conn,self.data,self.ids[0])
        self.assertNotEqual(current['id'],old_id);self.assertEqual(current['analysis']['status'],'ready')
        self.assertEqual([tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations WHERE id=?',(old_id,))],old_rows)
        for table in ('probe_attempts','learning_events','bank_views','bank_exposures'):
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_old_v1_input_never_gains_new_draft_fields(self):
        self.save_original('mathlens.question-topics/v1');self.change_catalogue()
        source=self.captured(rule='mathlens.question-topics/v1')['bank_questions'][0]
        self.assertNotIn('definition_review_draft',source)
        self.assertIn('definition_review_draft',self.captured()['bank_questions'][0])

    def test_old_v2_task_retry_and_delivery_keep_their_original_input_hash(self):
        self.save_original('mathlens.question-topics/v2');self.change_catalogue()
        with patch.object(annotations,'RULE_REVISION','mathlens.question-topics/v2'):
            self.f.start('annotate_questions',{'bank_ids':[self.ids[0]]})
        revision=self.f.task['input_revision']
        self.assertNotIn('definition_review_draft',json.loads(self.f.task['input_json'])['bank_questions'][0])
        task=retry_task(self.conn,self.root,self.data,self.f.task['id'])
        self.assertEqual(task['input_revision'],revision)
        bind_turn(self.conn,task['id'],'same-session',task['run_token'],'v2-retry');self.conn.commit()
        self.f.task=task;self.f.lease.update(run_token=task['run_token'],turn_id='v2-retry')
        self.f.read_annotation_material();self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.assertEqual(annotations.current(self.conn,self.data,self.ids[0])['rule_revision'],'mathlens.question-topics/v2')

    def test_parent_dependency_changes_are_explained(self):
        self.save_original()
        def revise_parent(value,node):
            parent=next(n for n in value['nodes'] if n['id']==node['parent_id'])
            parent['boundaries'].append('本章节范围条件变更，需核关联题。')
        self.change_catalogue(revise_parent)
        changes=self.captured()['bank_questions'][0]['definition_review_draft']['changed_knowledge']
        self.assertEqual(len(changes),1)
        self.assertIn('boundaries',changes[0]['changed_fields'])
        self.assertNotEqual(changes[0]['current_id'],'GS-04-001')

    def test_latest_unresolved_assessment_does_not_resurrect_older_ready_work(self):
        self.save_original();self.save_original(status='needs_review');self.change_catalogue()
        self.assertNotIn('definition_review_draft',self.captured()['bank_questions'][0])

    def test_a_moved_atom_includes_its_new_ancestor_context(self):
        self.save_original()
        self.change_catalogue(lambda value,node:node.update(parent_id='math1.calculus.integration'))
        changes=self.captured()['bank_questions'][0]['definition_review_draft']['changed_knowledge']
        atom=next(x for x in changes if x['previous_id']=='GS-04-001')
        parent=next(x for x in changes if x['current_id']=='math1.calculus.integration')
        self.assertEqual(atom['changed_fields'],['parent_id'])
        self.assertIsNone(parent['previous'])
        self.assertEqual(parent['current']['kind'],'chapter')
        self.assertIsNone(annotations.current(self.conn,self.data,self.ids[0]))


if __name__=='__main__':unittest.main()
