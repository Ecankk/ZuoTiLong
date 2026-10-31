from app.storage.boundaries import library_root
"""V1 compatibility needs saved reference evidence, not just a known rule name."""
import json
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import patch

import test_frozen_practice as frozen
import test_prepared_reuse as reuse
import test_question_annotations as annotation_fixtures
from app.bank import annotations
from app.bank.access import init_access
from app.learning.tasks import create_task,deliver,finish_task,receipt
from app.learning.practice_knowledge import require_reviewed_references


class PreparedReferencePolicyTests(unittest.TestCase):
    def setUp(self):
        self.case=reuse.PreparedReuseTests()
        with patch.object(annotations,'RULE_REVISION','mathlens.question-topics/v1'):
            self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.conn=self.case.conn;self.data=self.case.data;self.f=self.case.f

    def test_v1_original_reference_can_be_retained_after_bank_update(self):
        self.conn.execute('UPDATE bank_questions SET explanation=? WHERE id=?',('新资料版本。',frozen.BANK))
        self.case.start();self.case.read_original()
        count=self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0]
        self.case.save(self.case.retained())
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],count)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)

    def test_unknown_annotation_rule_does_not_gain_compatibility(self):
        self.conn.execute("UPDATE question_annotations SET rule_revision='unknown-rule'")
        self.case.start()
        with self.assertRaisesRegex(ValueError,'规则'):
            self.case.read_original()
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def reviewed_alias(self,different):
        alias='math3-2020-01'
        original=dict(self.conn.execute('SELECT * FROM bank_questions WHERE id=?',(frozen.BANK,)).fetchone())
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at) VALUES(?,?,?,?,?,'now')",
            (alias,'isolated-reference-alias','另一出处：求sin(x²)的导数。',original['answer'],
             '另一版本未经核验的解析。' if different else original['explanation']))
        original_image=library_root(self.data)/'bank-assets/analysis.png'
        (library_root(self.data)/'bank-assets/alias-analysis.png').write_bytes(original_image.read_bytes())
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',
                          (alias,'{}','bank-assets/question.png','bank-assets/alias-analysis.png',None))
        init_access(self.conn)
        self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)',(frozen.BANK,alias,'confirmed same mathematical question'))
        self.conn.commit()
        with patch.object(annotations,'RULE_REVISION','mathlens.question-topics/v1'):
            task=create_task(self.conn,self.f.root,self.data,'annotate_questions',None,
                'old-annotation-session',str(uuid.uuid4()),task_scope={'bank_ids':[frozen.BANK,alias]})
        lease=self.case.case.bind(task,'old-annotation-session')
        self.case.case.tool('read_bank',{'bank_id':frozen.BANK,'role':'all'},lease)
        self.case.case.tool('task_context',{'topic_ids':[frozen.TOPIC]},lease)
        value=annotation_fixtures.QuestionPreparationTests.annotation_result(SimpleNamespace(task=task))
        payload={'schema_version':'1.7','task_id':task['id'],'kind':task['kind'],'paper_id':None,
                 'input_revision':task['input_revision'],'author':'isolated-old-annotation','result':value}
        saved=deliver(self.conn,self.f.root,self.data,payload,lease);finish_task(self.conn,task['id']);self.conn.commit()
        row=self.conn.execute('SELECT * FROM question_annotations WHERE result_id=?',(saved['result_id'],)).fetchone()
        actual=annotations.materials(self.conn,self.data,alias)
        return row,{'bank_id':alias,'content_revision':actual['question']['sha256'],'resources':actual}

    def test_legacy_alias_with_different_references_cannot_inherit_review(self):
        annotation,manifest=self.reviewed_alias(True)
        with self.assertRaisesRegex(ValueError,'参考版本'):
            require_reviewed_references(self.conn,annotation,manifest)

    def test_same_references_with_other_paths_and_source_label_keep_review(self):
        annotation,manifest=self.reviewed_alias(False)
        require_reviewed_references(self.conn,annotation,manifest)

    def test_v1_fixed_materials_can_still_be_graded_after_rule_upgrade(self):
        attempt=self.case.base.submit()['attempt_id']
        captured=self.case.base.start_grade(attempt)
        self.assertEqual(captured['binding']['annotation_rule_revision'],'mathlens.question-topics/v1')
        self.case.base.grade(attempt)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],1)


if __name__=='__main__':unittest.main()
