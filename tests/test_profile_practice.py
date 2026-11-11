"""Profile tasks exercise the real frozen selection/grading path, with no model."""
import copy,json,unittest,uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
import database_fixture as server
import test_prepared_practice as prepared
from app.main import create_app
from app.learning.tasks import create_task,deliver,preflight,receipt,bind_turn
from app.agent.material_package import initial_inputs
from app.learning.profile_practice import quotas,choose


class ProfilePracticeTests(unittest.TestCase):
    def setUp(self):
        self.f=prepared.PreparedPracticeTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn=self.f.conn;self.root=self.f.f.root;self.data=self.f.data
        self.f.m.save();self.conn.commit()
        self.app=create_app(server.config(),agent_factory=None);self.addCleanup(self.app.state.runtime.close)
        self.rt=self.app.state.runtime;self.http=TestClient(self.app,base_url='http://127.0.0.1');self.addCleanup(self.http.close)
        self.body=dict(confirmed=True,request_id=str(uuid.uuid4()),size=5)

    def create(self):
        response=self.http.post('/api/practices/profile-batch',json=self.body)
        self.assertEqual(response.status_code,202,response.text)
        self.batch=response.json();return self.batch

    def start(self,kind='prepare_practice',attempt_id=None):
        job=self.conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(self.batch['job_id'],)).fetchone() if kind=='prepare_practice' else self.conn.execute('SELECT * FROM workflow_jobs WHERE attempt_id=? ORDER BY rowid DESC LIMIT 1',(attempt_id,)).fetchone()
        self.task=create_task(self.conn,self.root,self.data,kind,None,'fake-profile',job['request_id'],attempt_id,task_scope=json.loads(job['scope_json']) if job['scope_json'] else None,contract_version='1.12')
        bind_turn(self.conn,self.task['id'],'fake-profile',self.task['run_token'],'fake-turn');self.conn.commit()
        self.lease=dict(task_id=self.task['id'],session_id='fake-profile',run_token=self.task['run_token'],turn_id='fake-turn')
        packet=initial_inputs(self.conn,self.root,self.data,self.task['id'],self.lease);self.conn.commit()
        return json.loads(packet[0]['text']),packet

    def envelope(self,result):
        return dict(schema_version='1.12',task_id=self.task['id'],kind=self.task['kind'],paper_id=None,input_revision=self.task['input_revision'],author='fake',result=result)

    def selection(self,header):
        scope=header['selection'];gids=[t['goal']['id'] for t in scope['targets'] if prepared.BANK in t['candidate_ids']]
        self.assertTrue(gids,scope)
        return self.envelope(dict(selections=[dict(bank_id=prepared.BANK,goal_ids=gids,selection_reason='针对链式法则。',prompt='只求导并解释内导数。')],limitations={t['goal']['id']:'' if t['goal']['id'] in gids else '无适合候选' for t in scope['targets']}))

    def save_selection(self):
        self.create();header,packet=self.start();value=self.selection(header)
        self.assertFalse(any(i['type']=='localImage' for i in packet));self.assertTrue(header['materials_complete'])
        before=self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0]
        self.assertTrue(preflight(self.conn,self.root,self.data,value,self.lease)['valid'])
        self.assertIsNone(receipt(self.conn,self.task['id']))
        result=deliver(self.conn,self.root,self.data,value,self.lease);self.conn.commit()
        self.assertEqual(deliver(self.conn,self.root,self.data,value,self.lease)['result_id'],result['result_id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],before)
        return self.http.get('/api/practices/profile-batches/'+self.batch['batch_id']).json()['practice_ids'][0]

    def test_quotas_and_request_scope_idempotence(self):
        self.assertEqual([list(quotas(n).values()) for n in (5,8,10)],[[3,1,1],[4,2,2],[5,3,2]])
        targets=[dict(topic_id=str(i),category=c) for c in ('weak','review_due','uncovered') for i in range(10)]
        self.assertEqual(len(choose(targets,8)),8)
        batch=self.create()
        replay=self.http.post('/api/practices/profile-batch',json=self.body)
        self.assertEqual(replay.status_code,200,replay.text);self.assertTrue(replay.json()['reused'])
        self.assertEqual(replay.json()['batch_id'],batch['batch_id'])
        self.assertEqual(self.http.post('/api/practices/profile-batch',json=dict(self.body,size=8)).status_code,409)
        self.assertEqual(self.http.post('/api/practices/profile-batch',json=dict(self.body,request_id='bad')).status_code,400)
        self.assertEqual(self.http.post('/api/practices/profile-batch',json=dict(self.body,request_id=str(uuid.uuid4()),scope={'subject':'missing'})).status_code,404)
        self.assertEqual(self.http.get('/api/practices/profile-batches/missing').status_code,404)

    def test_complete_selection_snapshot_grade_and_profile_feedback(self):
        eid=self.save_selection()
        listing=self.http.get('/api/practices?source=profile&group_by=batch').json()
        self.assertEqual(listing['counts']['total'],1)
        card=listing['items'][0]['items'][0];self.assertEqual(card['origin'],'profile');self.assertIsNone(card['paper_id']);self.assertIsNone(card['latest_correctness'])
        detail=self.http.get('/api/practices/'+eid).json()
        self.assertNotIn('analysis_image',detail['question']);self.assertIn('submit',detail['actions'])
        self.assertEqual(card['access']['collection_label'],detail['practice']['access']['collection_label'])
        body=dict(response='先外层后内层求导。',request_id=str(uuid.uuid4()))
        response=self.http.post('/api/probes/'+eid+'/submit',json=body);self.assertEqual(response.status_code,201,response.text)
        aid=response.json()['attempt_id']
        self.assertEqual(self.http.post('/api/probes/'+eid+'/submit',json=body).json()['attempt_id'],aid)
        h,packet=self.start('grade_attempt',aid);self.assertTrue(h['materials_complete']);self.assertEqual(h['profile_practice']['id'],aid)
        self.assertEqual(h['assignment']['prompt'],'只求导并解释内导数。')
        self.assertTrue(any(p['type']=='localImage' for p in packet))
        # Changing the live library cannot replace a student's captured question.
        self.conn.execute("UPDATE bank_questions SET stem='unrelated later material' WHERE id=?",(prepared.BANK,));self.conn.commit()
        from app.agent.tools import execute
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            captured=json.loads(execute(self.root,self.data,'read_bank',dict(bank_id=prepared.BANK,role='all'),lease=self.lease)[0]['text'])
        self.assertIn('sin',captured['resources']['question']['text'])
        value=self.envelope(dict(attempt_id=aid,correct=True,answer_status='correct',feedback='回答正确，内导数已保留。',reference_reasoning='$2x\\cos(x^2)$',observations=[],first_error=None,possible_causes=[],topic_ids=[prepared.TOPIC],next_step='',needs_material=[]))
        self.assertTrue(preflight(self.conn,self.root,self.data,value,self.lease)['valid'])
        deliver(self.conn,self.root,self.data,value,self.lease);self.conn.commit()
        from app.learning.workflows import reconcile
        reconcile(self.conn,self.root,self.data);self.conn.commit()
        self.assertEqual(self.conn.execute("SELECT count(*) FROM workflow_jobs WHERE kind NOT IN ('prepare_practice','grade_attempt')").fetchone()[0],0)
        detail=self.http.get('/api/practices/'+eid).json();self.assertEqual(detail['practice']['latest_correctness'],'correct')
        self.assertTrue(detail['latest_attempt']['feedback_unread'])
        self.assertEqual(self.http.get('/api/practices/'+eid+'/attempts').json()['total'],1)
        profile=self.http.get('/api/profile/overview');self.assertEqual(profile.status_code,200,profile.text)
        self.assertEqual(profile.json()['totals']['unread_feedback_count'],1)
        title=profile.json()['feedback']['recent_items'][0]['title']
        self.assertIn('第1题',title);self.assertNotEqual(title,'画像选题')
        topic=self.http.get('/api/knowledge/topics/'+prepared.TOPIC);self.assertEqual(topic.status_code,200,topic.text)
        self.assertEqual(topic.json()['performance']['source_counts']['profile_practice'],1)
        mark=dict(source='profile_practice',attempt_id=aid,request_id=str(uuid.uuid4()),feedback_revision=detail['latest_attempt']['feedback_revision'])
        self.assertEqual(self.http.post('/api/feedback/read',json=mark).status_code,200)
        self.assertEqual(self.http.get('/api/profile/overview').json()['totals']['unread_feedback_count'],0)

    def test_selection_rechecks_late_uploaded_original_and_illegal_pair(self):
        self.create();header,_=self.start();value=self.selection(header)
        invalid=copy.deepcopy(value);invalid['result']['selections'][0]['goal_ids']=['not-provided']
        with self.assertRaisesRegex(ValueError,'not-provided'):preflight(self.conn,self.root,self.data,invalid,self.lease)
        self.conn.execute("UPDATE papers SET title='2020年数二',source_name='2020年数二.pdf' WHERE id='paper-test'");self.conn.commit()
        with self.assertRaisesRegex(ValueError,'原卷|上传|画像目标'):deliver(self.conn,self.root,self.data,value,self.lease)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM profile_practice_exercises').fetchone()[0],0)

    def test_no_choices_requires_limitations_and_publishes_no_empty_exercises(self):
        self.create();header,_=self.start()
        value=self.envelope(dict(selections=[],limitations={t['goal']['id']:'当前没有适合本次范围的候选。' for t in header['selection']['targets']}))
        deliver(self.conn,self.root,self.data,value,self.lease);self.conn.commit()
        detail=self.http.get('/api/practices/profile-batches/'+self.batch['batch_id']).json()
        self.assertEqual(detail['status'],'no_candidates');self.assertEqual(detail['practice_ids'],[])

    def test_retry_keeps_batch_and_scope_but_creates_new_task_and_session(self):
        self.create();self.start();old=self.task
        self.conn.execute("UPDATE learning_tasks SET status='failed',error='interrupted' WHERE id=?",(old['id'],))
        self.conn.execute("UPDATE workflow_jobs SET status='failed',task_id=? WHERE id=?",(old['id'],self.batch['job_id']));self.conn.commit()
        from app.learning.workflows import retry_job
        retry_job(self.conn,self.root,self.data,self.batch['job_id']);self.conn.commit()
        detail=self.http.get('/api/practices/profile-batches/'+self.batch['batch_id']).json()
        self.assertNotEqual(detail['job_id'],self.batch['job_id']);self.assertEqual(detail['status'],'queued')
        self.batch['job_id']=detail['job_id'];self.start()
        self.assertNotEqual(old['id'],self.task['id'])
        self.assertEqual(json.loads(old['input_json'])['task_scope'],json.loads(self.task['input_json'])['task_scope'])
        self.assertIsNone(receipt(self.conn,old['id']))

    def test_supplement_keeps_attempt_identity_history_and_marks_seen_feedback_assisted(self):
        eid=self.save_selection();body=dict(response='首次作答。',request_id=str(uuid.uuid4()))
        aid=self.http.post('/api/probes/'+eid+'/submit',json=body).json()['attempt_id']
        self.conn.execute('UPDATE profile_practice_attempts SET assessment_json=? WHERE id=?',(json.dumps({'correct':False,'feedback':'错误已说明。','topic_ids':[]}),aid));self.conn.commit()
        response=self.http.post('/api/attempts/'+aid+'/supplement',json=dict(response='补充计算。',request_id=str(uuid.uuid4())))
        self.assertEqual(response.status_code,200,response.text);self.assertEqual(response.json()['attempt_id'],aid)
        detail=self.http.get('/api/practices/'+eid).json()
        self.assertIsNone(detail['practice']['latest_correctness']);self.assertTrue(detail['latest_attempt']['answer_exposed'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM profile_practice_attempts').fetchone()[0],1)
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_versions WHERE kind='attempt' AND record_id=?",(aid,)).fetchone()[0],1)
