from pathlib import Path
import json
import tempfile
import threading
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.config import AppConfig
from app.main import create_app
from app.storage.database import Database
from app.agent.errors import BridgeConflict
from app.hosting import bind_socket

ROOT=Path(__file__).resolve().parents[1]


class OwnedAgent:
    def __init__(self,root,data):
        self.root,self.data=root,data;self.lock=threading.RLock()
        self.workflow_wakeup=threading.Event();self.closed=False;self.busy=False
    def close(self):self.closed=True
    def assert_user_write_allowed(self):
        if self.busy:raise BridgeConflict('active turn')
    def snapshot(self):return {'connected':False,'turns':[]}


class FastAPIAppTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'tmp',prefix='api-')
        self.data=Path(self.temp.name);self.dist=self.data/'dist';self.dist.mkdir()
        (self.dist/'index.html').write_text('<html>isolated MathLens</html>')
        self.config=AppConfig(ROOT,self.data,self.dist,self.data/'mathlens.db')
    def tearDown(self):self.temp.cleanup()
    def client(self,**kw):return TestClient(create_app(self.config,**kw),base_url='http://127.0.0.1')

    def test_lifespan_owns_one_agent_without_connecting_or_creating_remote_session(self):
        agents=[]
        def factory(root,data):
            agent=OwnedAgent(root,data);agents.append(agent);return agent
        app=create_app(self.config,agent_factory=factory)
        self.assertFalse(self.config.database.exists());self.assertEqual(agents,[])
        with TestClient(app,base_url='http://127.0.0.1') as http:
            self.assertEqual(http.get('/api/health').status_code,200)
            self.assertEqual(len(agents),1);self.assertFalse(agents[0].closed)
            self.assertEqual(http.get('/api/agent/state').json()['turns'],[])
            self.assertFalse((self.data/'agent-session.db').exists())
        self.assertTrue(agents[0].closed)

    def test_origin_host_static_and_unknown_api_boundaries(self):
        with self.client(agent_factory=None) as http:
            self.assertEqual(http.get('/api/bootstrap',headers={'Host':'attacker.test'}).status_code,403)
            self.assertEqual(http.post('/api/papers',json={'title':'x'},headers={'Origin':'https://evil.test'}).status_code,403)
            self.assertEqual(http.get('/api/unknown').status_code,404)
            self.assertEqual(http.get('/assets/missing.js').status_code,200)
            self.assertEqual(http.get('/topics/GS-01-073.higher-order-infinitesimal').status_code,200)
            self.assertEqual(http.get('/api').status_code,404)
            self.assertEqual(http.get('/some/frontend-route').status_code,200)
            self.assertEqual(http.get('/api/health').headers['cache-control'],'no-store')
            self.assertEqual(http.post('/api/reviews',json={}).status_code,400)
            self.assertEqual(http.get('/api/questions/../secret').status_code,404)

    def test_request_size_and_strict_boolean_validation(self):
        with self.client(agent_factory=None) as http:
            self.assertEqual(http.post('/api/screen',content=b'x'*(1024*1024+1)).status_code,400)
            self.assertEqual(http.post('/api/preferences',json={'study_type':True}).status_code,400)
            self.assertEqual(http.post('/api/preferences',json={'study_type':1,'mask_same_type':'false'}).status_code,400)
            self.assertEqual(http.post('/api/papers/no/archive',json={'confirmed':'true'}).status_code,400)

    def test_busy_mutations_fail_but_saved_reads_and_drafts_remain_available(self):
        agent=OwnedAgent(ROOT,self.data);agent.busy=True
        with self.client(bridge=agent,agent_factory=None,manage_agent=False) as http:
            self.assertEqual(http.post('/api/papers',json={'title':'not saved'}).status_code,409)
            self.assertEqual(http.get('/api/bootstrap').status_code,200)
            self.assertEqual(http.post('/api/drafts',json={'key':'answer:1','value':{'text':'local draft'}}).status_code,200)
            self.assertEqual(http.get('/api/drafts?key=answer:1').json()['value']['text'],'local draft')
        self.assertFalse(agent.closed)

    def test_import_collision_rolls_back_and_preserves_original_identity(self):
        with self.client(agent_factory=None) as http:
            original={'id':'original','source':'fixture','stem':'unchanged','answer':'1'}
            self.assertEqual(http.post('/api/bank/import',json={'questions':[original]}).status_code,201)
            response=http.post('/api/bank/import',json={'questions':[{'id':'new','stem':'must roll back'},dict(original,stem='replaced')]})
            self.assertEqual(response.status_code,400,response.text)
            with Database(self.config).session() as conn:
                self.assertEqual(conn.execute('SELECT stem FROM bank_questions WHERE id=?',('original',)).fetchone()[0],'unchanged')
                self.assertIsNone(conn.execute('SELECT id FROM bank_questions WHERE id=?',('new',)).fetchone())

    def test_pdf_upload_waits_for_confirmation_before_queueing_analysis(self):
        import pymupdf
        with pymupdf.open() as pdf:
            page=pdf.new_page()
            page.insert_text((50,70),'1. First question.\n2. Second question.')
            content=pdf.tobytes()
        # No bridge/dispatcher: queueing here remains local and isolated.
        with self.client(agent_factory=None) as http:
            with patch('app.services.papers.enqueue',side_effect=AssertionError('upload queued AI')):
                uploaded=http.post('/api/papers/import',files={'file':('fixture.pdf',content,'application/pdf')})
            self.assertEqual(uploaded.status_code,201,uploaded.text)
            result=uploaded.json();pid=result['paper']['id']
            self.assertFalse(result['agent_queued']);self.assertNotIn('job_id',result)
            self.assertEqual(http.get('/api/tasks').json()['items'],[])
            detail=http.get('/api/papers/'+pid).json()
            self.assertIn(detail['paper']['analysis_status'],('segmented','needs_review'))
            self.assertIsNone(detail['analysis']['report_id']);self.assertIn('analyze',detail['actions'])
            questions=http.get('/api/papers/'+pid+'/questions').json()['items']
            self.assertEqual([q['number'] for q in questions],['1','2'])
            corrected=http.post('/api/papers/'+pid+'/questions/correct',json={
                'confirmed':True,'questions':[{'number':q['number'],'question_ids':[q['id']]} for q in questions]})
            self.assertEqual(corrected.status_code,200,corrected.text)
            for body in ({},{'confirmed':False}):
                rejected=http.post('/api/papers/'+pid+'/analyze',json=body)
                self.assertEqual(rejected.status_code,400,rejected.text)
            self.assertEqual(http.get('/api/tasks').json()['items'],[])
            queued=http.post('/api/papers/'+pid+'/analyze',json={'confirmed':True})
            self.assertEqual(queued.status_code,201,queued.text)
            self.assertTrue(queued.json()['agent_queued'])
            reused=http.post('/api/papers/import',files={'file':('renamed.pdf',content,'application/pdf')})
            self.assertEqual(reused.status_code,200,reused.text)
            self.assertTrue(reused.json()['reused']);self.assertEqual(reused.json()['paper']['id'],pid)
            tasks=http.get('/api/tasks').json()['items']
            self.assertEqual(len(tasks),1);self.assertEqual(tasks[0]['paper_id'],pid)
            with Database(self.config).session() as conn:
                job=conn.execute('SELECT * FROM workflow_jobs').fetchone()
                self.assertEqual(job['kind'],'analyze_paper')
                self.assertEqual((job['auto_prepare'],job['index_after']),(1,1))
                self.assertEqual((job['practice_contract_version'],job['contract_version']),('1.9','2.0'))
                self.assertEqual(conn.execute('SELECT count(*) FROM papers').fetchone()[0],1)
                self.assertEqual(conn.execute('SELECT count(*) FROM learning_tasks').fetchone()[0],0)

    def test_two_apps_keep_paths_and_records_separate(self):
        other=AppConfig(ROOT,self.data/'other',self.dist,self.data/'other'/'mathlens.db')
        with self.client(agent_factory=None) as a,TestClient(create_app(other,agent_factory=None),base_url='http://127.0.0.1') as b:
            self.assertEqual(a.post('/api/papers',json={'title':'only app A'}).status_code,201)
            self.assertEqual(len(a.get('/api/papers').json()['papers']),1)
            self.assertEqual(b.get('/api/papers').json()['papers'],[])
            self.assertNotEqual(a.get('/api/health').json()['data_id'],b.get('/api/health').json()['data_id'])

    def test_asgi_knowledge_index_exposes_pending_not_legacy_judgement_titles(self):
        with self.client(agent_factory=None) as http:
            value=http.get('/api/knowledge').json()
            self.assertEqual(value['pending_sources'],[])
            self.assertEqual(len(value['nodes']),26)
            self.assertEqual(http.post('/api/knowledge/organize',json={}).json()['jobs'],[])

    def test_uvicorn_owns_bound_socket_and_falls_back_without_port_race(self):
        first,_=bind_socket('127.0.0.1',0)
        second=None
        try:
            port=first.getsockname()[1]
            second,failures=bind_socket('127.0.0.1',port,True)
            self.assertNotEqual(second.getsockname()[1],port)
            self.assertEqual(failures[0]['port'],port)
        finally:
            first.close()
            if second:second.close()
