import copy
import json
from contextlib import closing
import unittest
import os
import sqlite3
import subprocess
import sys

from PIL import Image
import test_learning_loop as fixtures
from app.learning.contracts import VERSION, validate_result, KINDS, result_schema
from app.learning.tasks import create_task, bind_turn, deliver, record_read, finish_task, resource_digest, task_record, digest, retry_task, receipt
from jsonschema import Draft202012Validator


class LearningTaskTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.LearningLoopTests()
        self.fixture.setUp()
        self.conn = self.fixture.conn
        self.data = self.fixture.root
        self.root = fixtures.ROOT
        self.kind = 'analyze_paper'
        self.task = None
        self.lease = None

    def tearDown(self):
        self.fixture.tearDown()

    def start(self, kind='analyze_paper', **kwargs):
        import uuid
        self.kind = kind
        self.task = create_task(self.conn, self.root, self.data, kind, 'paper-test',
                                'session-test', str(uuid.uuid4()), **kwargs)
        bind_turn(self.conn, self.task['id'], 'session-test', self.task['run_token'], 'turn-test')
        self.lease = {k: self.task[k] for k in ('session_id', 'run_token')}
        self.lease.update(task_id=self.task['id'], turn_id='turn-test')
        return self.task

    def envelope(self, result):
        version=json.loads(self.task['input_json']).get('contract_version',VERSION)
        if version=='2.0' and self.kind in ('analyze_paper','review_question'):
            result.setdefault('references',[])
        if self.kind=='prepare_practice':
            if version in ('1.3','1.4','1.5','1.6'):result.setdefault('retained_exercises', [])
            if version in ('1.5','1.6'):
                for goal in result.get('goals',[]):goal.setdefault('related_probe_ids',[])
        return {'schema_version': version, 'task_id': self.task['id'], 'kind': self.kind,
                'paper_id': 'paper-test', 'input_revision': self.task['input_revision'],
                'author': 'test-agent', 'result': result}

    def analysis(self):
        report = copy.deepcopy(self.fixture.report)
        report.pop('probes')
        report['review']={'status':'verified','issues':[]}
        for question in report['questions']:
            question.update(evidence_status='readable',correct_parts=['setup is valid'], first_error={'stage': 'calculation', 'step': 'step 2',
                            'evidence': 'visible arithmetic mismatch'}, knowledge=['bounds'],
                            reference_reasoning='Independent derivation: integrate the bounds.',
                            solution_guide={'entry_point':'Read the geometric bounds.',
                                            'strategy':'Translate the region before integrating.',
                                            'key_steps':['Identify each boundary.','Integrate over the resulting limits.'],
                                            'pitfalls':['Check whether the upper boundary changes.']},
                            cause_summary='The visible limits are wrong; a missed boundary is possible, but the underlying cause remains uncertain.',
                            fingerprint={'conditions': ['given region'], 'goal': 'evaluate integral',
                                         'methods': ['integration'], 'operations': ['bounds']},
                            answer_evidence={'student_work':'visible incorrect limits','student_state':'visible',
                                             'marking':'wrong','marking_note':'a correction identifies the limits'})
        return self.envelope({'completion': 'complete', 'report': report})

    def read_page(self):
        record_read(self.conn, self.lease, 'paper', 'paper-test', '1', self.fixture.digest)

    def apply_analysis(self):
        self.start(); self.read_page()
        value = deliver(self.conn, self.root, self.data, self.analysis(), self.lease)
        finish_task(self.conn, self.task['id'])
        self.conn.commit()
        return value

    def bank_read(self):
        image = self.data / 'unused.png'
        Image.new('RGB', (20, 20), 'white').save(image)
        record_read(self.conn, self.lease, 'bank', 'bank-test', 'question', resource_digest(image, self.data))

    def plan(self):
        goal = {'id': 'region', 'label': 'region understanding', 'question_numbers': [1, 2],
                'topic_ids': ['bounds'], 'stage': 'modeling', 'evidence': 'shared region errors',
                'priority': 1, 'decision': 'practice', 'reason': 'one targeted task covers both'}
        exercise = {'id': 'shared', 'goal_ids': ['region'], 'bank_id': 'bank-test',
                    'prompt': 'set up the bounds only', 'expected': '0 to 1',
                    'solution_note': 'derive the limits geometrically',
                    'selection_reason': 'tests the shared region representation', 'repeat_reason': None}
        return self.envelope({'goals': [goal], 'exercises': [exercise], 'limitations': []})

    def test_all_four_schemas_are_valid_and_unexpected_fields_rejected(self):
        for kind in KINDS:
            Draft202012Validator.check_schema(result_schema(kind))
        self.start()
        payload = self.analysis(); payload['result']['report']['questions'][0]['student_mastery'] = 100
        with self.assertRaisesRegex(ValueError, '结构不合法'):
            deliver(self.conn, self.root, self.data, payload, self.lease)
        self.assertIsNone(receipt(self.conn, self.task['id']))

    def test_final_text_cannot_create_receipt_and_material_must_be_read(self):
        self.start()
        with self.assertRaisesRegex(ValueError, '未成功保存'):
            finish_task(self.conn, self.task['id'])
        with self.assertRaisesRegex(ValueError, '尚未读取'):
            deliver(self.conn, self.root, self.data, self.analysis(), self.lease)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0], 0)

    def test_result_and_projection_are_atomic_and_repeat_delivery_is_idempotent(self):
        self.start(); self.read_page()
        payload = self.analysis()
        first = deliver(self.conn, self.root, self.data, payload, self.lease)
        events = self.conn.execute('SELECT COUNT(*) FROM learning_events').fetchone()[0]
        again = deliver(self.conn, self.root, self.data, payload, self.lease)
        self.assertEqual(first['result_id'], again['result_id'])
        self.assertTrue(again['reused'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM learning_events').fetchone()[0], events)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0], 1)
        finish_task(self.conn, self.task['id'])
        self.assertEqual(task_record(self.conn, self.task['id'])['status'], 'completed')

    def test_old_lease_cross_paper_and_changed_inputs_cannot_write(self):
        self.start(); self.read_page()
        for key in ('session_id', 'turn_id', 'run_token'):
            wrong = {**self.lease, key: 'old-value'}
            with self.assertRaisesRegex(ValueError, '旧连接'):
                deliver(self.conn, self.root, self.data, self.analysis(), wrong)
        wrong = self.analysis(); wrong['paper_id'] = 'other-paper'
        with self.assertRaisesRegex(ValueError, '任务范围'):
            deliver(self.conn, self.root, self.data, wrong, self.lease)
        self.conn.execute("UPDATE papers SET score=99 WHERE id='paper-test'")
        with self.assertRaisesRegex(ValueError, '材料已变化'):
            deliver(self.conn, self.root, self.data, self.analysis(), self.lease)
        self.assertIsNone(receipt(self.conn, self.task['id']))

    def test_projection_failure_rolls_back_saved_result(self):
        self.start(); self.read_page()
        payload = self.analysis()
        payload['result']['report']['questions'][0]['regions'][0]['bbox'] = [0, 0, 9999, 9999]
        with self.assertRaisesRegex(ValueError, '区域超界'):
            deliver(self.conn, self.root, self.data, payload, self.lease)
        self.assertIsNone(receipt(self.conn, self.task['id']))
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0], 0)

    def test_missing_evidence_is_preserved_as_unknown_without_fabricated_region(self):
        self.start();self.read_page()
        payload=self.analysis();payload['result']['completion']='partial'
        report=payload['result']['report'];report['limitations']=['Question 2 is not visible; upload its missing page.']
        question=report['questions'][1]
        question.update(regions=[],evidence_status='missing',correctness='unknown',first_error=None,
                        reference_answer='',reference_reasoning='',skill_events=[],hypotheses=[],
                        answer_evidence={'student_work':'','student_state':'unreadable','marking':'none','marking_note':''})
        report['review']={'status':'needs_review','issues':['Question 2 is missing']}
        deliver(self.conn,self.root,self.data,payload,self.lease)
        self.assertEqual(self.conn.execute('SELECT import_status FROM papers').fetchone()[0],'partial_analysis')
        saved=self.conn.execute("SELECT regions_json,correctness FROM questions WHERE number='2'").fetchone()
        self.assertEqual(json.loads(saved[0]),[])
        self.assertEqual(saved[1],'unknown')

    def test_multiple_original_questions_share_one_goal_and_exercise(self):
        self.apply_analysis(); self.start('prepare_practice'); self.bank_read()
        deliver(self.conn, self.root, self.data, self.plan(), self.lease)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM practice_goals').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM goal_questions').fetchone()[0], 2)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM diagnostic_probes').fetchone()[0], 1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM probe_goals').fetchone()[0], 1)
        payload = json.loads(self.conn.execute('SELECT payload_json FROM diagnostic_probes').fetchone()[0])
        self.assertEqual(payload['accepted'], [])

    def test_one_exercise_can_cover_two_goals_without_duplicate_attempts(self):
        self.apply_analysis();self.start('prepare_practice');self.bank_read()
        value=self.plan();goals=value['result']['goals']
        goals.append({**goals[0],'id':'second-stage','stage':'entry','question_numbers':[2]})
        value['result']['exercises'][0]['goal_ids'].append('second-stage')
        deliver(self.conn,self.root,self.data,value,self.lease)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM diagnostic_probes').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM probe_goals').fetchone()[0],2)

    def test_unknown_grade_can_be_replaced_after_supplement_without_duplicate_evidence(self):
        from app.learning.loop import submit_probe, supplement_attempt
        self.apply_analysis();self.start('prepare_practice');self.bank_read()
        deliver(self.conn,self.root,self.data,self.plan(),self.lease);finish_task(self.conn,self.task['id'])
        pid=self.conn.execute('SELECT id FROM diagnostic_probes').fetchone()[0]
        aid=submit_probe(self.conn,pid,{'response':'unreadable key step'})['attempt_id']
        self.start('grade_attempt',attempt_id=aid);self.bank_read()
        attempt=dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(aid,)).fetchone())
        record_read(self.conn,self.lease,'attempt',aid,'response',digest(attempt))
        result={'attempt_id':aid,'correct':None,'answer_status':'unknown','feedback':'Need the endpoint line.',
                'reference_reasoning':'','observations':[],'first_error':None,'possible_causes':[],
                'topic_ids':['bounds'],'next_step':'Provide only the missing line.','needs_material':['endpoint line']}
        deliver(self.conn,self.root,self.data,self.envelope(result),self.lease);finish_task(self.conn,self.task['id'])
        supplement_attempt(self.conn,aid,{'response':'endpoint value is 1'})
        self.start('grade_attempt',attempt_id=aid);self.bank_read()
        attempt=dict(self.conn.execute('SELECT * FROM probe_attempts WHERE id=?',(aid,)).fetchone())
        record_read(self.conn,self.lease,'attempt',aid,'response',digest(attempt))
        result.update(correct=True,answer_status='correct',feedback='The new visible step is correct.',
                      reference_reasoning='Evaluate the limits to obtain 1.',needs_material=[])
        deliver(self.conn,self.root,self.data,self.envelope(result),self.lease)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM probe_attempts').fetchone()[0],1)
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM learning_events WHERE kind='probe_success'").fetchone()[0],1)

    def test_empty_plan_is_valid_and_unknown_grading_is_supported(self):
        self.apply_analysis(); self.start('prepare_practice')
        deliver(self.conn, self.root, self.data, self.envelope({'goals': [], 'exercises': [],
                'limitations': ['No sufficiently verified candidate']}), self.lease)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM diagnostic_probes').fetchone()[0], 0)

    def test_retry_rotates_lease_without_losing_verified_reads(self):
        self.start(); self.read_page()
        from app.learning.tasks import fail_task
        fail_task(self.conn, self.task['id'], 'format error')
        new = retry_task(self.conn, self.root, self.data, self.task['id'])
        bind_turn(self.conn, new['id'], new['session_id'], new['run_token'], 'new-turn')
        with self.assertRaisesRegex(ValueError, '旧连接'):
            deliver(self.conn, self.root, self.data, self.analysis(), self.lease)
        self.lease.update(run_token=new['run_token'], turn_id='new-turn')
        deliver(self.conn, self.root, self.data, self.analysis(), self.lease)

    def test_marking_and_original_answer_cannot_be_confused(self):
        self.start()
        for evidence in (
            {'student_work':'C','student_state':'visible','marking':'wrong','marking_note':'red correction B'},
            {'student_work':'不会','student_state':'not_attempted','marking':'wrong','marking_note':'red correction 0'},
        ):
            payload=self.analysis();q=payload['result']['report']['questions'][0]
            q.update(correctness='correct',first_error=None,skill_events=[],answer_evidence=evidence)
            with self.assertRaisesRegex(ValueError,'不能标正确'):
                validate_result(payload,'analyze_paper')
        payload=self.analysis();q=payload['result']['report']['questions'][0]
        q.update(correctness='unknown',first_error=None)
        with self.assertRaisesRegex(ValueError,'正误也记为未知'):
            validate_result(payload,'analyze_paper')
        q['correctness']='wrong'
        validate_result(payload,'analyze_paper')
        q.update(correctness='correct',skill_events=[])
        payload['result']['report']['review']={'status':'needs_review','issues':['Independent proof disagrees with the marking']}
        validate_result(payload,'analyze_paper')

    def test_new_analysis_requires_evidence_but_old_contract_remains_readable(self):
        self.start();payload=self.analysis()
        report=payload['result']['report'];report.pop('review')
        for q in report['questions']:q.pop('answer_evidence')
        with self.assertRaisesRegex(ValueError,'required property'):
            validate_result(payload,'analyze_paper')
        payload['schema_version']='1.0'
        validate_result(payload,'analyze_paper')
        with self.assertRaises(ValueError):deliver(self.conn,self.root,self.data,payload,self.lease)

    def test_detailed_guide_and_cause_are_required_without_fabricating_causes(self):
        self.start()
        for field in ('solution_guide','cause_summary'):
            payload=self.analysis();payload['result']['report']['questions'][0].pop(field)
            with self.assertRaisesRegex(ValueError,'required property'):
                validate_result(payload,'analyze_paper')
            payload['schema_version']='1.1'
            validate_result(payload,'analyze_paper')
        payload=self.analysis();q=payload['result']['report']['questions'][0]
        q['cause_summary']=' '
        with self.assertRaisesRegex(ValueError,'可能原因'):
            validate_result(payload,'analyze_paper')
        q['cause_summary']='No derivation is visible, so the original cause cannot be distinguished; check the region representation first.'
        q['hypotheses']=[]
        validate_result(payload,'analyze_paper')
        q['solution_guide']=None
        with self.assertRaisesRegex(ValueError,'切入点'):
            validate_result(payload,'analyze_paper')

    def test_blank_work_is_included_for_practice_without_a_fabricated_math_error(self):
        self.start();payload=self.analysis();q=payload['result']['report']['questions'][0]
        q.update(first_error=None,answer_evidence={'student_work':'','student_state':'not_attempted',
                 'marking':'none','marking_note':''},skill_events=[{'skill_id':'bounds','label':'No work is visible','kind':'incomplete'}])
        validate_result(payload,'analyze_paper')
        q['correctness']='unknown'
        with self.assertRaisesRegex(ValueError,'纳入错题补强'):
            validate_result(payload,'analyze_paper')
        q['correctness']='wrong';q['skill_events'][0]['kind']='exam_error'
        with self.assertRaisesRegex(ValueError,'空白只支持未完成'):
            validate_result(payload,'analyze_paper')

    def test_unresolved_analysis_cannot_start_practice(self):
        import uuid
        self.start();self.read_page();payload=self.analysis()
        payload['result']['report']['review']={'status':'needs_review','issues':['Cannot distinguish original choice from correction']}
        deliver(self.conn,self.root,self.data,payload,self.lease);finish_task(self.conn,self.task['id']);self.conn.commit()
        with self.assertRaisesRegex(ValueError,'尚未核对通过'):
            create_task(self.conn,self.root,self.data,'prepare_practice','paper-test','session-test',str(uuid.uuid4()))
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM learning_tasks WHERE kind='prepare_practice'").fetchone()[0],0)

    def test_selected_plan_is_bound_to_the_analysis_it_actually_read(self):
        from app.learning.loop import loop_snapshot, submit_probe
        self.fixture.apply()
        self.apply_analysis()
        self.assertFalse(loop_snapshot(self.conn)['practice_states'][0]['is_current'])
        with self.assertRaisesRegex(ValueError,'先点击筛选题目'):
            submit_probe(self.conn,'paper-test-probe-test',{'response':'visible work'})
        self.start('prepare_practice')
        self.bank_read()
        plan=self.plan();plan['result']['exercises']=[]
        plan['result']['retained_exercises']=[{'probe_id':'paper-test-probe-test','goal_ids':['region']}]
        deliver(self.conn,self.root,self.data,plan,self.lease)
        finish_task(self.conn,self.task['id'])
        self.assertTrue(loop_snapshot(self.conn)['practice_states'][0]['is_current'])
        submit_probe(self.conn,'paper-test-probe-test',{'response':'visible work'})
        self.start();self.read_page();payload=self.analysis()
        payload['result']['report']['summary']='A new verified interpretation'
        deliver(self.conn,self.root,self.data,payload,self.lease)
        finish_task(self.conn,self.task['id'])
        self.assertFalse(loop_snapshot(self.conn)['practice_states'][0]['is_current'])
        with self.assertRaisesRegex(ValueError,'先点击筛选题目'):
            submit_probe(self.conn,'paper-test-probe-test',{'response':'more work'})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],1)

    def test_transport_release_invalidates_ticket_but_preserves_same_turn_reads(self):
        from app.learning.tasks import rekey_task
        self.start();self.read_page()
        token=rekey_task(self.conn,self.task['id'],self.lease['run_token'])
        with self.assertRaisesRegex(ValueError,'旧连接'):
            deliver(self.conn,self.root,self.data,self.analysis(),self.lease)
        self.lease['run_token']=token
        deliver(self.conn,self.root,self.data,self.analysis(),self.lease)

    def test_cli_delivers_using_same_transaction_and_rejects_stale_ticket(self):
        self.start();self.read_page();self.conn.commit()
        result_file=self.data/'result.json';result_file.write_text(json.dumps(self.analysis()),encoding='utf8')
        ticket_file=self.data/'ticket.json'
        ticket_file.write_text(json.dumps({**self.lease,'run_token':'stale-ticket'}),encoding='utf8')
        command=[sys.executable,'-X','utf8',str(self.root/'scripts/agent_tasks.py'),'deliver',str(result_file),'--ticket',str(ticket_file)]
        env={**os.environ,'MATHLENS_DATA_DIR':str(self.data)}
        bad=subprocess.run(command,cwd=self.root,env=env,capture_output=True,text=True,encoding='utf8')
        self.assertNotEqual(bad.returncode,0)
        ticket_file.write_text(json.dumps(self.lease),encoding='utf8')
        good=subprocess.run(command,cwd=self.root,env=env,capture_output=True,text=True,encoding='utf8')
        self.assertEqual(good.returncode,0,good.stderr)
        with closing(sqlite3.connect(self.fixture.conn.execute('PRAGMA database_list').fetchone()[2])) as stored:
            self.assertEqual(stored.execute('SELECT COUNT(*) FROM learning_results').fetchone()[0],1)
            self.assertEqual(stored.execute('SELECT COUNT(*) FROM agent_reports').fetchone()[0],1)


if __name__ == '__main__':
    unittest.main()
