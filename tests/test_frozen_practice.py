from app.storage.boundaries import workspace_config,connect_workspace
from app.storage.boundaries import library_root
"""Selected materials survive bank updates, grading and protected display."""
from contextlib import closing
from pathlib import Path
import hashlib,json,sqlite3,unittest
from unittest.mock import patch
from PIL import Image
import database_fixture as server
import test_prepared_practice as fixtures
from app.config import AppConfig
from app.storage.database import Database
from app.storage.practice_materials import load,image_path
from app.learning.practice_knowledge import binding_for,bind_attempt,grading_version
from app.learning.tasks import deliver,finish_task
from app.learning.loop import submit_probe,loop_snapshot
from app.services.practice import PracticeService,queue_attempt_grading

BANK='math2-2020-01'
TOPIC='GS-04-001'


class FrozenPracticeTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.PreparedPracticeTests();self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.f=self.case.f;self.conn=self.case.conn;self.data=self.case.data
        self.case.start();self.case.read()
        saved=deliver(self.conn,self.f.root,self.data,self.case.payload(),self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.probe_id=self.conn.execute('SELECT probe_id FROM practice_question_bindings WHERE result_id=?',(saved['result_id'],)).fetchone()[0]
        self.binding=binding_for(self.conn,self.probe_id)
        config=AppConfig(self.f.root,self.data,self.f.root/'dist',server.DB_PATH)
        self.service=PracticeService(config,Database(config))

    def submit(self):return self.service.submit(self.probe_id,{'response':'f′(x)=2x cos(x²)'})

    def start_grade(self,attempt_id):
        self.f.start('grade_attempt',attempt_id=attempt_id,contract_version='1.9')
        return json.loads(self.f.task['input_json'])['grading_knowledge']

    def grade(self,attempt_id):
        self.case.tool('read_attempt',{'attempt_id':attempt_id})
        materials=self.case.tool('read_bank',{'bank_id':BANK,'role':'all'})
        self.case.tool('task_context',{'topic_ids':[TOPIC]})
        payload=self.f.envelope({'attempt_id':attempt_id,'correct':True,'answer_status':'correct','feedback':'保留了内层导数，步骤正确。',
            'reference_reasoning':'设u=x²，df/dx=cos(u)·2x=2x cos(x²)。',
            'observations':[{'step':'链式法则','stage':'formula','status':'valid','evidence':'写出了内层导数2x。'}],
            'first_error':None,'possible_causes':[],'topic_ids':[TOPIC],'next_step':'后续自然观察。','needs_material':[]})
        saved=deliver(self.conn,self.f.root,self.data,payload,self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit();return materials,saved

    def test_submission_and_grade_job_capture_the_selected_version(self):
        result=self.submit()
        decision=self.conn.execute('SELECT * FROM practice_attempt_materials WHERE attempt_id=?',(result['attempt_id'],)).fetchone()
        self.assertEqual(decision['binding_result_id'],self.binding['binding_result_id'])
        job=self.conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(result['job']['id'],)).fetchone()
        self.assertEqual(job['contract_version'],'1.9');self.assertIsNone(job['task_id'])

    def test_direct_grade_entry_cannot_downgrade_a_bound_attempt_to_current_library_materials(self):
        from app.learning.workflows import enqueue
        from app.learning.tasks import create_task
        import uuid
        attempt=self.submit()['attempt_id']
        job=enqueue(self.conn,self.f.root,self.data,'grade_attempt','paper-test',str(uuid.uuid4()),attempt)
        self.assertEqual(job['contract_version'],'1.9')
        self.f.start('grade_attempt',attempt_id=attempt)
        self.assertEqual(json.loads(self.f.task['input_json'])['contract_version'],'1.9')
        with self.assertRaisesRegex(ValueError,'必须使用1.9'):
            create_task(self.conn,self.f.root,self.data,'grade_attempt','paper-test','test-session',
                        str(uuid.uuid4()),attempt_id=attempt,contract_version='1.6')

    def test_failed_handoff_rolls_back_attempt_and_material_decision(self):
        before={t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('probe_attempts','practice_attempt_materials','workflow_jobs')}
        with patch('app.services.practice.enqueue',side_effect=ValueError('handoff failed')):
            with self.assertRaisesRegex(ValueError,'handoff failed'):self.submit()
        self.assertEqual(before,{t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in before})

    def test_grading_uses_original_materials_after_live_question_and_reference_change(self):
        original=load(self.data,self.binding['snapshot_key'],self.binding['snapshot_sha256'])
        Image.new('RGB',(40,40),'yellow').save(library_root(self.data)/'bank-assets/question.png')
        Image.new('RGB',(40,40),'red').save(library_root(self.data)/'bank-assets/analysis.png')
        self.conn.execute('UPDATE bank_questions SET stem=?,explanation=? WHERE id=?',('另一个题目。','另一个参考版本。',BANK));self.conn.commit()
        attempt=self.submit()['attempt_id'];scope=self.start_grade(attempt)
        self.assertEqual(scope['materials']['resources']['question']['text'],original['resources']['question']['text'])
        materials,_=self.grade(attempt)
        question=next(r for r in materials['resources'] if r['role']=='question')
        self.assertEqual(question['text'],'求 f(x)=sin(x²) 的导数。')
        self.assertTrue(json.loads(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(attempt,)).fetchone()[0])['correct'])

    def test_missing_reference_does_not_require_student_to_transcribe_a_solution(self):
        path=image_path(self.data,self.binding,'analysis')
        self.assertTrue(path.resolve().is_relative_to((self.data/'practice-materials').resolve()));path.unlink()
        attempt=self.submit()['attempt_id'];scope=self.start_grade(attempt)
        self.assertEqual([r['role'] for r in scope['unavailable_references']],['analysis'])
        materials,_=self.grade(attempt)
        self.assertNotIn('analysis',[r['role'] for r in materials['resources']])

    def test_missing_original_question_keeps_submission_and_prevents_wrong_version_grading(self):
        path=image_path(self.data,self.binding,'question')
        self.assertTrue(path.resolve().is_relative_to((self.data/'practice-materials').resolve()));path.unlink()
        attempt=self.submit()['attempt_id']
        with self.assertRaisesRegex(ValueError,'快照'):self.start_grade(attempt)
        self.assertIsNotNone(self.conn.execute('SELECT id FROM probe_attempts WHERE id=?',(attempt,)).fetchone())
        self.assertIsNone(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(attempt,)).fetchone()[0])

    def test_retried_legacy_submission_cannot_acquire_a_new_material_binding(self):
        result=submit_probe(self.conn,self.probe_id,{'response':'an older unversioned response'})
        bind_attempt(self.conn,result['attempt_id'],reused=True);self.conn.commit()
        self.assertEqual(grading_version(self.conn,result['attempt_id']),'1.6')
        job=queue_attempt_grading(self.conn,result['attempt_id'],self.f.root,self.data)
        self.assertEqual(self.conn.execute('SELECT contract_version FROM workflow_jobs WHERE id=?',(job['id'],)).fetchone()[0],'1.6')

    def test_supplement_preserves_original_version_and_independent_attempt_snapshot(self):
        result=self.submit();attempt=result['attempt_id']
        from app.bank.access import reveal
        reveal(self.conn,BANK,'analysis',True);self.conn.commit()
        self.service.supplement(attempt,{'response':'补充内层导数的说明。'})
        self.assertEqual(binding_for(self.conn,self.probe_id,attempt)['snapshot_sha256'],self.binding['snapshot_sha256'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],1)
        versions=[json.loads(r[0]) for r in self.conn.execute("SELECT payload FROM record_versions WHERE kind='attempt' AND record_id=?",(attempt,))]
        self.assertTrue(any(not v['answer_exposed'] for v in versions))

    def test_unrelated_directory_growth_does_not_repeat_or_discard_grading(self):
        attempt=self.submit()['attempt_id'];self.start_grade(attempt)
        self.case.m.change('math1.probability.testing',definition='An unrelated mathematical boundary.')
        self.grade(attempt)
        self.assertTrue(json.loads(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(attempt,)).fetchone()[0])['correct'])

    def test_relevant_definition_change_rejects_grading_without_overwriting_attempt(self):
        attempt=self.submit()['attempt_id'];self.start_grade(attempt)
        self.case.m.change(TOPIC,conditions=['A changed chain-rule condition.'])
        with self.assertRaisesRegex(ValueError,'定义.*变化'):self.grade(attempt)
        self.assertIsNone(self.conn.execute('SELECT assessment_json FROM probe_attempts WHERE id=?',(attempt,)).fetchone()[0])

    def test_http_exercise_uses_snapshot_while_library_uses_current_bank(self):
        old=image_path(self.data,self.binding,'question').read_bytes()
        Image.new('RGB',(40,40),'yellow').save(library_root(self.data)/'bank-assets/question.png')
        self.conn.commit()
        from http_support import client
        with client() as http:
            response=http.get('/api/bank/'+BANK+'/question',params={'probe_id':self.probe_id})
            self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.content,old)
            current=http.get('/api/bank/'+BANK+'/question',params={'view':'library'})
            self.assertEqual(current.status_code,200);self.assertNotEqual(current.content,old)
            wrong=http.get('/api/bank/'+BANK+'/question',params={'probe_id':'missing'})
            self.assertEqual(wrong.status_code,404)
            mixed=http.get('/api/bank/'+BANK+'/question',params={'probe_id':self.probe_id,'view':'library'})
            self.assertEqual(mixed.status_code,400)
        payload=next(p for p in loop_snapshot(self.conn)['probes'] if p['id']==self.probe_id)
        self.assertIn('probe_id='+self.probe_id,payload['question_image'])

    def test_snapshot_backup_restore_keeps_grading_materials_when_original_files_are_absent(self):
        attempt=self.submit()['attempt_id'];self.conn.commit()
        from app.storage.maintenance import backup,restore
        archive=backup(self.data,self.f.root)['path'];destination=self.data/'restored-frozen-materials'
        restore(archive,destination)
        with closing(connect_workspace(workspace_config(destination),library_write=True)) as restored:
            restored.row_factory=sqlite3.Row
            binding=binding_for(restored,self.probe_id,attempt)
            material=load(destination,binding['snapshot_key'],binding['snapshot_sha256'])
            self.assertEqual(material['content_revision'],self.binding['content_revision'])
            self.assertEqual(grading_version(restored,attempt),'1.9')
            self.assertEqual(restored.execute('PRAGMA foreign_key_check').fetchall(),[])
