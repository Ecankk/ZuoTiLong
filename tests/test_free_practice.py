import json,uuid,unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
import database_fixture as server
import test_learning_loop as fixtures
from app.config import AppConfig
from app.main import create_app
from app.bank.access import reveal,save_preferences

class FreePracticeTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LearningLoopTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn=self.f.conn
        self.conn.execute("UPDATE bank_questions SET answer='B',explanation='reference',stem='unique searchable question' WHERE id='bank-test'")
        self.conn.execute("UPDATE bank_resources SET metadata_json=?,question_path='' WHERE bank_id='bank-test'",(json.dumps({'question_type':'choice'}),));self.conn.commit()
        self.app=create_app(AppConfig(server.ROOT,server.DATA,server.DIST,server.DB_PATH),agent_factory=None)
        self.http=TestClient(self.app,base_url='http://127.0.0.1');self.addCleanup(self.app.state.runtime.close);self.addCleanup(self.http.close)
        self.url='/api/bank/bank-test/practice'

    def submit(self,**body):
        return self.http.post(self.url+'/attempts',json={'request_id':str(uuid.uuid4()),**body})

    def test_choice_repeat_exposure_idempotence_and_history(self):
        self.assertEqual(self.http.get(self.url).status_code,200)
        body={'choice':'B','request_id':str(uuid.uuid4())}
        first=self.http.post(self.url+'/attempts',json=body);self.assertEqual(first.status_code,200,first.text)
        a=first.json();self.assertTrue(a['assessment']['correct']);self.assertFalse(a['answer_exposed'])
        self.assertEqual(a,self.http.post(self.url+'/attempts',json=body).json())
        self.assertEqual(self.http.post(self.url+'/attempts',json={**body,'choice':'A'}).status_code,409)
        second=self.submit(choice='A').json();self.assertFalse(second['assessment']['correct']);self.assertTrue(second['answer_exposed'])
        self.assertEqual(self.http.get(self.url+'/attempts').json()['total'],2)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],0)
        self.assertEqual(self.http.get('/api/profile').json()['free_practice']['total'],2)
        self.assertEqual(self.http.post('/api/preferences',json={'include_free_practice':False}).status_code,200)
        self.assertEqual(self.http.get('/api/profile').json()['free_practice']['total'],0)

    def test_fill_normalization_or_ai_and_complete_one_delivery(self):
        self.conn.execute("UPDATE bank_resources SET metadata_json=? WHERE bank_id='bank-test'",(json.dumps({'question_type':'fill'}),))
        self.conn.execute("UPDATE bank_questions SET answer=? WHERE id='bank-test'",(r'$\frac{1}{2}$',));self.conn.commit()
        self.assertTrue(self.submit(response=r' \dfrac{1}{2} ').json()['assessment']['correct'])
        value=self.submit(response='0.5');self.assertEqual(value.status_code,200,value.text)
        value=value.json();self.assertIsNone(value['assessment']);self.assertIsNotNone(value['job'])
        self.assertIsNone(value['materials']['reference'])
        from app.learning.tasks import create_task,bind_turn,deliver,preflight
        job=self.conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(value['job']['id'],)).fetchone()
        from app.learning.workflows import guard
        self.assertEqual(guard(self.conn,server.ROOT,server.DATA,'grade_attempt',None,value['id']),json.loads(job['guard_json']))
        task=create_task(self.conn,server.ROOT,server.DATA,'grade_attempt',None,'fake-session',job['request_id'],value['id'],workflow_id=job['workflow_id'],contract_version='1.11')
        bind_turn(self.conn,task['id'],'fake-session',task['run_token'],'fake-turn')
        lease=dict(task_id=task['id'],session_id='fake-session',run_token=task['run_token'],turn_id='fake-turn')
        from app.agent.material_package import initial_inputs
        packet=initial_inputs(self.conn,server.ROOT,server.DATA,task['id'],lease)
        header=json.loads(packet[0]['text']);self.assertTrue(header['materials_complete']);self.assertIn('role_method',header)
        from app.agent.tools import execute
        self.conn.execute("UPDATE bank_questions SET stem='new library text' WHERE id='bank-test'");self.conn.commit()
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            fixed=json.loads(execute(server.ROOT,server.DATA,'read_bank',{'bank_id':'bank-test','role':'all'},lease=lease)[0]['text'])
            self.assertEqual(fixed['resources']['question']['text'],'unique searchable question')
            work=json.loads(execute(server.ROOT,server.DATA,'read_attempt',{'attempt_id':value['id']},lease=lease)[0]['text'])
            self.assertEqual(work['response'],'0.5')
        result=dict(attempt_id=value['id'],correct=True,answer_status='correct',feedback='数学等价',reference_reasoning='$0.5=1/2$',observations=[],first_error=None,possible_causes=[],topic_ids=[],next_step='',needs_material=[])
        envelope=dict(schema_version='1.11',kind='grade_attempt',paper_id=None,task_id=task['id'],input_revision=task['input_revision'],author='fake',result=result)
        self.assertTrue(preflight(self.conn,server.ROOT,server.DATA,envelope,lease)['valid'])
        saved=deliver(self.conn,server.ROOT,server.DATA,envelope,lease);self.conn.commit();self.assertIn('result_id',saved)
        from app.learning.workflows import reconcile
        reconcile(self.conn,server.ROOT,server.DATA);self.conn.commit()
        self.assertEqual(self.conn.execute('SELECT status FROM workflow_jobs WHERE id=?',(job['id'],)).fetchone()[0],'completed')
        self.assertTrue(self.http.get(self.url+'/attempts').json()['items'][0]['assessment']['correct'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM workflow_jobs WHERE kind!='grade_attempt'").fetchone()[0],0)

    def test_reserved_masked_search_and_submission(self):
        self.conn.execute("UPDATE bank_identity SET math_type=1,year='2025',number=1 WHERE bank_id='bank-test'")
        self.conn.execute('DELETE FROM bank_views');self.conn.commit()
        self.assertEqual(self.http.get('/api/bank?q=unique').json()['total'],0)
        self.assertEqual(self.submit(choice='B').status_code,403)
        reveal(self.conn,'bank-test','question',True);self.conn.commit()
        self.assertEqual(self.http.get('/api/bank?q=unique').json()['total'],1)
        save_preferences(self.conn,{'reserved':[{'math_type':1,'year':'2025'}]});self.conn.commit()
        self.assertEqual(self.http.get('/api/bank?q=unique').json()['total'],0)
        self.assertEqual(self.submit(choice='B').status_code,403)

    def test_missing_choice_reference_queues_ai_and_invalid_requests(self):
        self.assertIsNone(self.http.get(self.url).json()['reference'])
        self.conn.execute("UPDATE bank_questions SET answer='' WHERE id='bank-test'");self.conn.commit()
        result=self.submit(choice='B');self.assertEqual(result.status_code,200,result.text)
        self.assertIsNotNone(result.json()['job']);self.assertIsNone(result.json()['assessment'])
        self.assertEqual(self.submit(choice='Z').status_code,400)
        self.assertEqual(self.http.post(self.url+'/attempts',json={'request_id':'bad','response':'a'}).status_code,400)

    def test_bulk_visibility_matches_single_policy_including_alias_reservation(self):
        from app.bank.access import viewable_ids,access,init_access
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('alias','test','same searchable text','now')")
        init_access(self.conn)
        self.conn.execute("INSERT INTO bank_links VALUES('bank-test','alias','confirmed identity')")
        self.conn.execute("UPDATE bank_identity SET math_type=1,year='2025',number=1 WHERE bank_id='alias'")
        save_preferences(self.conn,{'reserved':[{'math_type':1,'year':'2025'}]});self.conn.commit()
        expected={r[0] for r in self.conn.execute('SELECT id FROM bank_questions') if (lambda s:s['can_view'] and not s['reserved'])(access(self.conn,r[0]))}
        self.assertEqual(viewable_ids(self.conn),expected)
        self.assertEqual(self.http.get('/api/bank?q=searchable').json()['total'],0)

    def test_snapshot_survives_library_change_and_personal_backup(self):
        self.submit(choice='B')
        self.conn.execute("UPDATE bank_questions SET stem='replacement' WHERE id='bank-test'");self.conn.commit()
        self.assertEqual(self.http.get(self.url).json()['question']['question_text'],'unique searchable question')
        self.assertEqual(self.http.get(self.url+'/attempts').json()['items'][0]['materials']['question']['question_text'],'unique searchable question')
        self.conn.execute("DELETE FROM bank_identity WHERE bank_id='bank-test'");self.conn.commit()
        self.assertEqual(self.http.get(self.url).json()['question']['question_text'],'unique searchable question')
        from app.learning.free_practice import counts
        self.assertEqual(counts(self.conn)['independent_correct'],1)
        # Exercise the actual backup entry, then inspect its SQLite snapshot.
        response=self.http.post('/api/maintenance/backup',json={'confirmed':True})
        self.assertEqual(response.status_code,200,response.text)
        import zipfile,sqlite3,tempfile
        with zipfile.ZipFile(response.json()['path']) as archive:
            self.assertTrue(any(n.startswith('practice-materials/') for n in archive.namelist()))
            with tempfile.TemporaryDirectory(dir=server.DATA) as folder:
                target=Path(folder)/'saved.db';target.write_bytes(archive.read(server.DB_PATH.name))
                from contextlib import closing
                with closing(sqlite3.connect(target)) as db:self.assertEqual(db.execute('SELECT count(*) FROM free_practice_attempts').fetchone()[0],1)

    def test_proof_images_topics_receipts_and_cleanup(self):
        self.conn.execute("UPDATE bank_resources SET metadata_json=? WHERE bank_id='bank-test'",(json.dumps({'question_type':'proof'}),));self.conn.commit()
        from io import BytesIO
        from PIL import Image
        from app.storage.images import save_answer_image
        image=BytesIO();Image.new('RGB',(40,40),'white').save(image,format='PNG')
        iid=save_answer_image(self.conn,server.DATA,image.getvalue())['id'];self.conn.commit()
        with patch('app.bank.annotations.current',return_value={'analysis':{'bindings':[{'topic_id':'math1.calculus.functions-limits'}]}}):
            value=self.submit(response='my work',image_ids=[iid],image_roles={iid:'own_work'}).json()
        self.assertIsNotNone(value['job'])
        from app.storage.maintenance import cleanup_images
        self.assertEqual(cleanup_images(self.conn,server.DATA,min_age=-1)['moved'],0)
        from app.learning.tasks import create_task,bind_turn,deliver
        task=create_task(self.conn,server.ROOT,server.DATA,'grade_attempt',None,'fake',str(uuid.uuid4()),value['id'],contract_version='1.11')
        bind_turn(self.conn,task['id'],'fake',task['run_token'],'turn')
        lease=dict(task_id=task['id'],session_id='fake',run_token=task['run_token'],turn_id='turn')
        from app.agent.material_package import initial_inputs
        packet=initial_inputs(self.conn,server.ROOT,server.DATA,task['id'],lease)
        self.assertTrue(any(x['type']=='localImage' for x in packet))
        requirements='\n'.join(json.loads(packet[0]['text'])['requirements'])
        self.assertIn('feedback只写1–3句结论',requirements)
        self.assertIn('本次未附事后批改图片',requirements)
        result=dict(attempt_id=value['id'],correct=True,answer_status='correct',feedback='正确',reference_reasoning='checked',observations=[],first_error=None,possible_causes=[],topic_ids=['math1.calculus.functions-limits'],next_step='',needs_material=[])
        envelope=dict(schema_version='1.11',kind='grade_attempt',paper_id=None,task_id=task['id'],input_revision=task['input_revision'],author='fake',result=result)
        deliver(self.conn,server.ROOT,server.DATA,envelope,lease);self.conn.commit()
        topic=self.http.get('/api/knowledge/topics/math1.calculus.functions-limits');self.assertEqual(topic.status_code,200,topic.text)
        self.assertEqual(topic.json()['performance']['source_counts']['free_practice']['independent_correct'],1)
        self.assertEqual(topic.json()['performance']['successes'],1)
        self.http.post('/api/preferences',json={'include_free_practice':False})
        self.assertEqual(self.http.get('/api/knowledge/topics/math1.calculus.functions-limits').json()['performance']['successes'],0)

    def test_normalization_does_not_remove_other_latex_commands(self):
        from app.learning.free_practice import normal,choice
        self.assertEqual(normal(r'$\left(\dfrac{1}{2}\right)$'),r'(\frac{1}{2})')
        self.assertEqual(normal(r'\rightarrow'),r'\rightarrow')
        self.assertEqual(choice(r'$\mathrm{B}$'),'B')

if __name__=='__main__':unittest.main()
