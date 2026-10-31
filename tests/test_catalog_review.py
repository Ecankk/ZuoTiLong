import copy
import json
import unittest
import uuid

from app.knowledge import catalog
from app.knowledge.maintenance import normalize_scope
from app.learning.tasks import create_task, finish_task, task_package
from app.learning.workflows import enqueue


class CatalogueReviewTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp()
        self.conn=self.f.conn
        self.scope={'source_version_id':self.f.f.sid,'source_ids':['GS-04-001']}

    def tearDown(self):self.f.tearDown()

    def test_absent_note_keeps_the_existing_scope_and_task_snapshot(self):
        self.assertEqual(normalize_scope('maintain_catalog',self.scope),self.scope)
        self.f.start('maintain_catalog',self.scope)
        captured=json.loads(self.f.task['input_json'])
        self.assertEqual(captured['task_scope'],self.scope)
        self.f.tool('task_context',{'source_ids':['GS-04-001']})
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.maintenance_result())})
        finish_task(self.conn,self.f.task['id'])

    def test_invalid_or_unscoped_review_notes_are_rejected(self):
        for note in ('','  ',None,False,{},'x'*4001):
            with self.subTest(note_type=type(note).__name__),self.assertRaisesRegex(ValueError,'复核说明'):
                normalize_scope('maintain_catalog',{**self.scope,'review_note':note})
        with self.assertRaises(ValueError):
            normalize_scope('annotate_questions',{'bank_ids':['bank-test'],'review_note':'核对本题。',
                                                 'source_ids':['GS-04-001']})
        with self.assertRaises(ValueError):
            normalize_scope('maintain_catalog',{**self.scope,'force_arbitrary_nodes':True})

    def test_reviewer_note_is_visible_but_cannot_bypass_reading_or_change_source_rows(self):
        original=self.conn.execute('SELECT payload_json FROM knowledge_source_entries').fetchall()
        scope={**self.scope,'review_note':'  请独立核对内外层可导条件，而非只看结论。  '}
        self.f.start('maintain_catalog',scope)
        package=task_package(self.conn,self.f.task['id'])
        self.assertEqual(package['input']['task_scope']['review_note'],scope['review_note'].strip())
        with self.assertRaisesRegex(ValueError,'尚未读取'):
            self.f.tool('apply_report',{'result':self.f.envelope(self.f.maintenance_result())})
        self.assertIsNone(catalog.active_id(self.conn))
        self.assertEqual(self.conn.execute('SELECT payload_json FROM knowledge_source_entries').fetchall(),original)

    def test_recheck_updates_one_existing_node_and_retains_old_release_and_student_facts(self):
        self.f.prepare_catalog()
        previous=catalog.document(self.conn)
        scope={**self.scope,'review_note':'核对当前定义的适用条件；有依据时只修本来源的既有原子。'}
        self.f.start('maintain_catalog',scope)
        self.f.tool('task_context',{'source_ids':['GS-04-001']})
        self.f.tool('task_context',{'topic_ids':['GS-04-001']})
        result=self.f.maintenance_result()
        result['node_changes'][0]['review_note']='重新核对：内外函数分别在相应点可导；沿用原ID。'
        self.f.tool('apply_report',{'result':self.f.envelope(result)})
        self.assertNotEqual(catalog.active_id(self.conn),previous['id'])
        self.assertEqual(catalog.document(self.conn,previous['id']),previous)
        self.assertEqual(len(catalog.document(self.conn)['document']['nodes']),len(previous['document']['nodes']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)

    def test_same_task_identity_cannot_replace_the_captured_review_question(self):
        self.f.start('maintain_catalog',{**self.scope,'review_note':'first review question'})
        with self.assertRaisesRegex(ValueError,'不能更换作用域'):
            create_task(self.conn,self.f.root,self.f.data,'maintain_catalog',None,'same-session',
                        self.f.task['request_id'],task_scope={**self.scope,'review_note':'different review question'})

    def test_pending_jobs_with_different_review_questions_do_not_merge(self):
        first=enqueue(self.conn,self.f.root,self.f.data,'maintain_catalog',None,str(uuid.uuid4()),
                      task_scope={**self.scope,'review_note':'first review question'})
        same=enqueue(self.conn,self.f.root,self.f.data,'maintain_catalog',None,str(uuid.uuid4()),
                     task_scope={**self.scope,'review_note':'first review question'})
        other=enqueue(self.conn,self.f.root,self.f.data,'maintain_catalog',None,str(uuid.uuid4()),
                      task_scope={**self.scope,'review_note':'different review question'})
        self.assertEqual(first['id'],same['id'])
        self.assertNotEqual(first['id'],other['id'])
        with self.assertRaisesRegex(ValueError,'不能更换作用域'):
            enqueue(self.conn,self.f.root,self.f.data,'maintain_catalog',None,first['request_id'],
                    task_scope={**self.scope,'review_note':'replace original question'})


if __name__=='__main__':unittest.main()
