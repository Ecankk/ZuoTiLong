from app.storage.boundaries import workspace_config,connect_workspace
"""Practice reuse keeps one question/attempt and never bypasses source validity."""
import json
import sqlite3
import unittest
import uuid
from contextlib import closing
from unittest.mock import patch

from PIL import Image

import test_learning_tasks as fixtures
from app.bank.access import init_access, register_identity
from app.learning.loop import loop_snapshot
from app.learning.tasks import bind_turn, create_task, deliver, finish_task, receipt, record_read, resource_digest, task_package


class PracticeReuseTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LearningTaskTests()
        self.f.setUp()
        self.conn=self.f.conn
        self.f.apply_analysis()

    def tearDown(self):
        self.f.tearDown()

    def start(self,kind='prepare_practice',paper='paper-test',version=None):
        with patch('app.learning.tasks.VERSION',version or '1.5'):
            task=create_task(self.conn,self.f.root,self.f.data,kind,paper,
                             'session-test',str(uuid.uuid4()))
        bind_turn(self.conn,task['id'],'session-test',task['run_token'],'turn-test')
        self.f.task=task
        self.f.kind=kind
        self.f.lease={k:task[k] for k in ('session_id','run_token')}
        self.f.lease.update(task_id=task['id'],turn_id='turn-test')
        return task

    def save(self,payload):
        payload['paper_id']=self.f.task['paper_id']
        saved=deliver(self.conn,self.f.root,self.f.data,payload,self.f.lease)
        finish_task(self.conn,self.f.task['id'])
        return saved

    def source_plan(self):
        source=self.conn.execute("SELECT source_path FROM papers WHERE id='paper-test'").fetchone()[0]
        self.conn.execute('INSERT INTO papers(id,title,source_path,created_at) VALUES(?,?,?,?)',
                          ('paper-old','Earlier paper',source,'now'))
        self.start('analyze_paper','paper-old')
        record_read(self.conn,self.f.lease,'paper','paper-old','1',self.f.fixture.digest)
        self.save(self.f.analysis())
        self.start(paper='paper-old')
        self.f.bank_read()
        self.save(self.f.plan())
        return self.conn.execute("SELECT id FROM diagnostic_probes WHERE paper_id='paper-old'").fetchone()[0]

    def related_plan(self,pid):
        value=self.f.plan()
        value['result']['exercises']=[]
        value['result']['goals'][0]['related_probe_ids']=[pid]
        return value

    def counts(self):
        return {name:self.conn.execute('SELECT count(*) FROM '+name).fetchone()[0]
                for name in ('diagnostic_probes','probe_attempts','learning_events')}

    def test_cross_paper_shared_reference_keeps_one_record_and_exposes_no_hidden_content(self):
        pid=self.source_plan()
        self.conn.execute("UPDATE bank_identity SET math_type=1,year='2025',number=1 WHERE bank_id='bank-test'")
        self.conn.execute('DELETE FROM bank_views')
        before=self.counts()
        self.start()
        self.f.bank_read()
        value=self.related_plan(pid)
        value['result']['goals'].append({**value['result']['goals'][0],'id':'second-operation',
                                        'question_numbers':[2]})
        self.save(value)
        self.assertEqual(before,self.counts())
        snap=loop_snapshot(self.conn)
        current=[g for g in snap['goals'] if g['paper_id']=='paper-test']
        self.assertEqual(len(current),2)
        self.assertTrue(all(g['related_probe_ids']==[pid] for g in current))
        probe=next(p for p in snap['probes'] if p['id']==pid)
        self.assertFalse(probe['access']['can_view'])
        for key in ('prompt','question_image','expected','solution_note','selection_reason'):
            self.assertNotIn(key,probe)

    def test_historical_reference_requires_current_question_and_analysis_read(self):
        pid=self.source_plan()
        Image.new('RGB',(24,18),'blue').save(self.f.data/'analysis.png')
        self.conn.execute("UPDATE bank_resources SET analysis_path='analysis.png' WHERE bank_id='bank-test'")
        self.start()
        self.f.bank_read()
        value=self.related_plan(pid)
        with self.assertRaisesRegex(ValueError,'尚未读取.*analysis'):
            deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute("SELECT count(*) FROM practice_goals WHERE paper_id='paper-test'").fetchone()[0],0)
        record_read(self.conn,self.f.lease,'bank','bank-test','analysis',
                    resource_digest(self.f.data/'analysis.png',self.f.data))
        self.save(value)

    def reject_source(self,change,expected):
        pid=self.source_plan()
        change(pid)
        self.start()
        self.f.bank_read()
        package=task_package(self.conn,self.f.task['id'])
        self.assertFalse(next(p for p in package['historical_exercises'] if p['probe_id']==pid)['can_reuse'])
        before=self.counts()
        with self.assertRaisesRegex(ValueError,expected):
            deliver(self.conn,self.f.root,self.f.data,self.related_plan(pid),self.f.lease)
        self.assertEqual(before,self.counts())
        self.assertEqual(self.conn.execute("SELECT count(*) FROM practice_goals WHERE paper_id='paper-test'").fetchone()[0],0)

    def test_archived_source_cannot_be_reopened_through_reference(self):
        self.reject_source(lambda _:self.conn.execute("UPDATE papers SET archived_at='now' WHERE id='paper-old'"),'归档')

    def test_retired_exercise_cannot_be_reopened_through_reference(self):
        self.reject_source(lambda pid:self.conn.execute('INSERT INTO retired_probes VALUES(?,?,?)',(pid,'retired','now')),'停用')

    def test_new_source_analysis_makes_old_reference_unavailable(self):
        def change(_):
            self.start('analyze_paper','paper-old')
            record_read(self.conn,self.f.lease,'paper','paper-old','1',self.f.fixture.digest)
            payload=self.f.analysis()
            payload['result']['report']['summary']='Revised source analysis'
            self.save(payload)
        self.reject_source(change,'分析已变化')

    def test_nonexistent_reference_is_rejected_without_partial_plan(self):
        self.start()
        with self.assertRaisesRegex(ValueError,'不存在'):
            deliver(self.conn,self.f.root,self.f.data,self.related_plan('not-a-probe'),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def test_same_paper_reference_must_use_retained_membership(self):
        self.start();self.f.bank_read();self.save(self.f.plan())
        pid=self.conn.execute('SELECT id FROM diagnostic_probes').fetchone()[0]
        self.start();self.f.bank_read()
        value=self.related_plan(pid)
        value['result']['retained_exercises']=[{'probe_id':pid,'goal_ids':['region']}]
        with self.assertRaisesRegex(ValueError,'本卷练习'):
            deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)

    def test_confirmed_cross_source_duplicate_pending_question_is_not_created_again(self):
        self.source_plan()
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('math2-2020-01','test','same question','now')")
        self.conn.execute("INSERT INTO bank_resources VALUES('math2-2020-01','{}','unused.png',NULL,NULL)")
        init_access(self.conn)
        register_identity(self.conn,'bank-test',1,'2020',1,self.f.data/'unused.png')
        register_identity(self.conn,'math2-2020-01',2,'2020',1,self.f.data/'unused.png')
        self.start()
        record_read(self.conn,self.f.lease,'bank','math2-2020-01','question',
                    resource_digest(self.f.data/'unused.png',self.f.data))
        value=self.f.plan()
        value['result']['exercises'][0].update(bank_id='math2-2020-01',repeat_reason='different source')
        with self.assertRaisesRegex(ValueError,'已有待做记录'):
            deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],1)

    def test_one_question_links_multiple_current_goals_and_limitations_are_visible(self):
        self.start();self.f.bank_read()
        value=self.f.plan()
        value['result']['goals'].append({**value['result']['goals'][0],'id':'entry','question_numbers':[1]})
        value['result']['exercises'][0]['goal_ids'].append('entry')
        value['result']['limitations']=['Only the setup is assigned; final arithmetic is not tested.']
        self.save(value)
        snap=loop_snapshot(self.conn)
        self.assertEqual(len(snap['probes']),1)
        self.assertEqual(set(snap['probes'][0]['linked_goal_ids']),{g['id'] for g in snap['goals']})
        self.assertEqual(snap['practice_states'][0]['limitations'],value['result']['limitations'])

    def test_decisions_match_actual_arrangement(self):
        self.start();self.f.bank_read()
        value=self.f.plan()
        value['result']['exercises']=[]
        with self.assertRaisesRegex(ValueError,'须关联实际'):
            deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        value['result']['goals'][0]['decision']='monitor'
        self.save(value)

    def test_no_candidate_with_reusable_question_is_rejected(self):
        pid=self.source_plan()
        self.start();self.f.bank_read()
        value=self.related_plan(pid)
        value['result']['goals'][0]['decision']='no_candidate'
        with self.assertRaisesRegex(ValueError,'不能同时声称无候选'):
            deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)

    def test_in_flight_old_contract_remains_deliverable_without_new_fields(self):
        for version in ('1.3','1.4'):
            with self.subTest(version=version):
                self.start(version=version)
                value=self.f.plan()
                self.assertNotIn('related_probe_ids',value['result']['goals'][0])
                self.f.bank_read()
                old=self.conn.execute('SELECT id FROM diagnostic_probes').fetchone()
                if old:
                    value['result']['exercises']=[]
                    value['result']['retained_exercises']=[{'probe_id':old[0],'goal_ids':['region']}]
                self.save(value)

    def test_backup_restore_preserves_related_identity_and_can_continue_source(self):
        from app.storage.maintenance import backup, restore
        from app.learning.loop import submit_probe
        pid=self.source_plan()
        self.start();self.f.bank_read();self.save(self.related_plan(pid))
        self.conn.commit()
        saved=backup(self.f.data,self.f.root)
        target=self.f.data/'restored-copy'
        restore(saved['path'],target)
        with closing(connect_workspace(workspace_config(target),library_write=True)) as restored,restored:
            restored.row_factory=sqlite3.Row
            snap=loop_snapshot(restored)
            goal=next(g for g in snap['goals'] if g['paper_id']=='paper-test')
            self.assertEqual(goal['related_probe_ids'],[pid])
            self.assertEqual(len(snap['probes']),1)
            self.assertEqual(restored.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)
            submit_probe(restored,pid,{'response':'Continue the same source exercise after restore.'})
            self.assertEqual(restored.execute('SELECT count(*) FROM probe_attempts WHERE probe_id=?',(pid,)).fetchone()[0],1)


if __name__=='__main__':
    unittest.main()
