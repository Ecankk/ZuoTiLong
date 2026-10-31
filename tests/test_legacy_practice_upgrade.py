from app.storage.boundaries import library_root
"""Old selectors need original image evidence before acquiring a fixed version."""
import json,unittest
from unittest.mock import patch
from PIL import Image
import test_prepared_practice as fixtures
from app.learning.tasks import deliver,finish_task,receipt
from app.learning.loop import submit_probe
from app.learning.practice_knowledge import binding_for,bind_attempt,grading_version,require_existing_read

TOPIC=fixtures.TOPIC
BANK=fixtures.BANK


class LegacyPracticeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.PreparedPracticeTests();self.case.setUp();self.addCleanup(self.case.tearDown)
        self.f=self.case.f;self.conn=self.case.conn;self.data=self.case.data
        self.case.m.save()
        self.f.start('prepare_practice',contract_version='1.6')
        for role in ('question','analysis'):self.case.tool('read_bank',{'bank_id':BANK,'role':role})
        value=self.case.payload();value['result']['exercises'][0].pop('annotation_id')
        saved=deliver(self.conn,self.f.root,self.data,value,self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.origin=self.f.task['id'];self.source_result=saved['result_id']
        self.pid=self.conn.execute('SELECT id FROM diagnostic_probes WHERE json_extract(payload_json,\'$.source_result_id\')=?',(self.source_result,)).fetchone()[0]
        self.attempt=submit_probe(self.conn,self.pid,{'response':'Original independent response'})['attempt_id']
        bind_attempt(self.conn,self.attempt,reused=True);self.conn.commit()
        self.original=dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(self.attempt,)).fetchone())
        self.probes=self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0]

    def start(self):self.f.start('prepare_practice',contract_version='1.9')

    def read(self):
        self.case.tool('task_context',{'topic_ids':[TOPIC]})
        return self.case.tool('read_bank',{'bank_id':BANK,'probe_id':self.pid,'role':'all'})

    def value(self):
        value=self.case.payload();value['result']['exercises']=[]
        value['result']['retained_exercises']=[{'probe_id':self.pid,'goal_ids':['chain']}]
        return value

    def save(self):
        value=self.value();saved=deliver(self.conn,self.f.root,self.data,value,self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit();return saved

    def unchanged(self):
        self.assertEqual(dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(self.attempt,)).fetchone()),self.original)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],self.probes)
        self.assertEqual(grading_version(self.conn,self.attempt),'1.6')

    def test_original_read_hash_and_ready_annotation_upgrade_only_the_exercise(self):
        self.start();material=self.read();self.save()
        binding=binding_for(self.conn,self.pid)
        self.assertEqual(binding['legacy_origin']['task_id'],self.origin)
        self.assertEqual(binding['legacy_origin']['result_id'],self.source_result)
        self.assertEqual(binding['annotation_id'],self.case.annotation['id'])
        self.assertEqual(material['material_binding']['legacy_origin'],binding['legacy_origin'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_question_bindings').fetchone()[0],1)
        self.unchanged()

    def test_reading_a_provisional_snapshot_does_not_upgrade_any_learning_record(self):
        self.start();self.read()
        self.assertIsNone(binding_for(self.conn,self.pid));self.unchanged()

    def test_missing_origin_read_keeps_old_answer_without_inventing_a_version(self):
        self.conn.execute("DELETE FROM task_reads WHERE task_id=? AND kind='bank' AND role='question'",(self.origin,))
        self.start()
        with self.assertRaisesRegex(ValueError,'原选题阅读凭据'):self.read()
        self.assertIsNone(receipt(self.conn,self.f.task['id']));self.assertIsNone(binding_for(self.conn,self.pid))
        self.unchanged()

    def test_changed_question_image_is_not_accepted_as_the_old_exercise(self):
        Image.new('RGB',(40,40),'orange').save(library_root(self.data)/'bank-assets/question.png')
        self.start()
        with self.assertRaisesRegex(ValueError,'原任务阅读版本不一致'):self.read()
        self.assertIsNone(binding_for(self.conn,self.pid));self.unchanged()

    def test_unchanged_image_with_stale_mathematical_annotation_requires_preparation(self):
        self.conn.execute('UPDATE bank_questions SET stem=? WHERE id=?',('A new text that has not been reviewed.',BANK))
        self.start()
        with self.assertRaisesRegex(ValueError,'标注尚未就绪'):self.read()
        self.assertIsNone(binding_for(self.conn,self.pid));self.unchanged()

    def test_result_failure_rolls_back_membership_and_legacy_binding_together(self):
        self.start();self.read()
        before={t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0]
                for t in ('learning_results','practice_goals','practice_plan_members','practice_question_bindings')}
        calls=[]
        def verify(*args):
            calls.append(True)
            if len(calls)==2:raise ValueError('handoff failure after plan projection')
            return require_existing_read(*args)
        with patch('app.learning.practice_knowledge.require_existing_read',side_effect=verify):
            with self.assertRaisesRegex(ValueError,'handoff failure'):
                deliver(self.conn,self.f.root,self.data,self.value(),self.f.lease)
        self.assertEqual(before,{t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before})
        self.assertIsNone(receipt(self.conn,self.f.task['id']));self.unchanged()

    def test_saved_legacy_binding_can_be_reused_without_creating_another_binding(self):
        self.start();self.read();self.save()
        original=binding_for(self.conn,self.pid)
        self.start();self.read();self.save()
        self.assertEqual(binding_for(self.conn,self.pid),original)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_question_bindings').fetchone()[0],1)
        self.unchanged()
