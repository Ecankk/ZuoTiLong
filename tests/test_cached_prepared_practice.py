"""Real 1.9 task guards use imported origin without forged source tasks."""
import json
from types import SimpleNamespace
import unittest

from app.bank import annotations,annotation_packages as packages
from app.learning.tasks import deliver,finish_task
from app.learning.practice_knowledge import binding_for
from app.services.practice import PracticeService
from app.config import AppConfig
from app.storage.database import Database


class CachedPreparedPracticeTests(unittest.TestCase):
    def setUp(self):
        from test_prepared_practice import PreparedPracticeTests,BANK,TOPIC
        self.case=PreparedPracticeTests();self.case.setUp();self.addCleanup(self.case.tearDown)
        self.conn=self.case.conn;self.data=self.case.data;self.f=self.case.f;self.bank=BANK;self.topic=TOPIC
        package=packages.export_package(self.conn,self.data)
        # Isolated target simulation: retain the fixture's original task
        # history, but remove the local analysis. No personal DB is accessed.
        self.conn.execute('DELETE FROM annotation_provenance')
        self.conn.execute('DELETE FROM question_annotation_topics')
        self.conn.execute('DELETE FROM question_annotation_links')
        self.conn.execute('DELETE FROM question_annotations');self.conn.commit()
        old_tasks=self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0]
        p=packages.preview(self.conn,self.data,package)
        packages.import_package(self.conn,self.data,package,trusted_sha256=package['sha256'],
                                expected_preview_sha256=p['preview_sha256'],confirmed=True)
        self.conn.commit();self.sha=package['sha256']
        self.case.annotation=annotations.current(self.conn,self.data,BANK)
        self.assertIn('cache_provenance',self.case.annotation)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],old_tasks)

    def save_plan(self):
        self.case.start()
        self.case.tool('task_context',{'topic_ids':[self.topic]})
        found=self.case.tool('catalog',{'topic_ids':[self.topic]})
        self.assertEqual(found['items'][0]['annotation_id'],self.case.annotation['id'])
        material=self.case.tool('read_bank',{'bank_id':self.bank,'role':'all'})
        self.assertIn('cache_provenance',material['prepared_question'])
        self.assertNotIn('reference_reasoning',material['prepared_question'])
        self.assertTrue(material['resources'])
        saved=deliver(self.conn,self.f.root,self.data,self.case.payload(),self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        return self.conn.execute('SELECT probe_id FROM practice_question_bindings WHERE result_id=?',(saved['result_id'],)).fetchone()[0]

    def test_imported_origin_passes_recall_material_and_binding_gates_without_fake_proof(self):
        pid=self.save_plan();binding=binding_for(self.conn,pid)
        self.assertEqual(binding['annotation_id'],self.case.annotation['id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)
        self.assertEqual(list(self.conn.execute('PRAGMA foreign_key_check')),[])

    def test_frozen_practice_can_be_graded_after_library_update_and_index_disable(self):
        from test_frozen_practice import FrozenPracticeTests
        import database_fixture as server
        pid=self.save_plan()
        config=AppConfig(self.f.root,self.data,self.f.root/'dist',server.DB_PATH)
        service=PracticeService(config,Database(config))
        example=SimpleNamespace(case=self.case,f=self.f,conn=self.conn,data=self.data,probe_id=pid,service=service)
        self.conn.execute('UPDATE bank_questions SET stem=?,answer=? WHERE id=?',('different later question','different later answer',self.bank))
        packages.set_enabled(self.conn,self.sha,False,confirmed=True);self.conn.commit()
        attempt=FrozenPracticeTests.submit(example)['attempt_id']
        captured=FrozenPracticeTests.start_grade(example,attempt)
        self.assertEqual(captured['materials']['resources']['question']['text'],'求 f(x)=sin(x²) 的导数。')
        FrozenPracticeTests.grade(example,attempt)
        self.assertTrue(json.loads(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(attempt,)).fetchone()[0])['correct'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],1)

    def test_material_change_during_selection_rejects_imported_annotation_without_attempt(self):
        self.case.start();self.case.tool('task_context',{'topic_ids':[self.topic]})
        self.case.tool('catalog',{'topic_ids':[self.topic]});self.case.tool('read_bank',{'bank_id':self.bank,'role':'all'})
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?',('new unreviewed reference',self.bank));self.conn.commit()
        with self.assertRaisesRegex(ValueError,'ready|标注|变化|当前版本'):
            deliver(self.conn,self.f.root,self.data,self.case.payload(),self.f.lease)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)


if __name__=='__main__':unittest.main()
