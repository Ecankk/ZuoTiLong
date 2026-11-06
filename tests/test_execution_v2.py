"""Disposable sessions and backend material packages, no real app-server."""
import copy,json,time,unittest,uuid
from unittest.mock import patch
import database_fixture as server
import test_prepared_practice as prepared
from app.agent.bridge import CodexBridge
from app.agent.material_package import initial_inputs
from app.learning.tasks import task_record,deliver,receipt,preflight
from app.bank.access import save_preferences,reveal

class FakeServer:
    instances=[]
    def __init__(self,root,data,notify,disconnected):
        self.calls=[];self.sent=[];self.notify=notify;self.closed=False
        self.instances.append(self)
    def request(self,method,params):
        self.calls.append((method,params))
        if method=='account/read':return {'account':{'type':'chatgpt'}}
        if method=='model/list':return {'data':[{'model':'gpt-6-luna','displayName':'Luna','supportedReasoningEfforts':[{'reasoningEffort':e} for e in ('high','xhigh')]}]}
        if method=='thread/start':return {'thread':{'id':'session-'+uuid.uuid4().hex},'model':params['model'],'reasoningEffort':params['config']['model_reasoning_effort']}
        if method=='turn/start':return {'turn':{'id':'turn-'+uuid.uuid4().hex}}
        return {}
    def send(self,message):self.sent.append(message)
    def close(self):self.closed=True

class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.case=prepared.PreparedPracticeTests();self.case.setUp();self.addCleanup(self.case.tearDown)
        self.f=self.case.f;self.conn=self.case.conn;self.data=self.case.data;self.root=self.f.root
        from app.learning.loop import apply_report
        report=json.loads(self.conn.execute('SELECT report_json FROM agent_reports ORDER BY rowid DESC LIMIT 1').fetchone()[0])
        report['probes']=[]
        for q in report['questions']:
            q.update(evidence_status='readable',correct_parts=['有效的起步'],
                first_error={'stage':'calculation','step':'2','evidence':'漏乘内层导数'},
                answer_evidence={'student_work':'可见的遗漏','student_state':'visible','marking':'wrong','marking_note':'事后批改'},
                solution_guide={'entry_point':'识别复合函数','strategy':'逐层求导','key_steps':['先外后内'],'pitfalls':['漏乘内导数']},cause_summary='内导数遗漏')
        apply_report(self.conn,'paper-test',report,self.root)
        self.case.m.save();self.conn.commit()
        self.patch=patch('app.agent.tools.connection',lambda data:server.connect());self.patch.start();self.addCleanup(self.patch.stop)
    def wait(self,predicate):
        end=time.monotonic()+5
        while not predicate():
            if time.monotonic()>end:self.fail('execution timed out')
            time.sleep(.01)
    def selection(self):
        self.f.start('prepare_practice',contract_version='1.10')
        self.task=self.f.task;self.lease=self.f.lease
        items=initial_inputs(self.conn,self.root,self.data,self.task['id'],self.lease);self.conn.commit()
        scope=json.loads(self.task['input_json'])['selection']
        return items,scope
    def selection_payload(self,scope):
        goals=[t['goal']['id'] for t in scope['targets'] if prepared.BANK in t['candidate_ids']]
        self.assertTrue(goals)
        return self.f.envelope({'selections':[{'bank_id':prepared.BANK,'goal_ids':goals,
            'selection_reason':'检验链式求导中的内层导数。','prompt':r'计算$f(x)=\sin(x^2)$的导数并说明内层导数。'}],
            'limitations':{t['goal']['id']:'' if t['goal']['id'] in goals else '无合适候选' for t in scope['targets']}})
    def save_selection(self):
        _,scope=self.selection();payload=self.selection_payload(scope)
        saved=deliver(self.conn,self.root,self.data,payload,self.lease);self.conn.commit()
        return saved
    def bridge(self):
        b=CodexBridge(self.root,self.data,FakeServer);self.addCleanup(b.close)
        b.connect();self.wait(lambda:b.connected);return b
    def test_summary_package_can_preflight_then_save_without_image_reads(self):
        items,scope=self.selection();self.assertFalse(any(i['type']=='localImage' for i in items))
        payload=self.selection_payload(scope)
        before=self.conn.execute('SELECT count(*) FROM learning_results').fetchone()[0]
        folder=self.data/'practice-materials';files=list(folder.rglob('*')) if folder.exists() else []
        self.assertTrue(preflight(self.conn,self.root,self.data,payload,self.lease)['valid'])
        self.assertEqual(before,self.conn.execute('SELECT count(*) FROM learning_results').fetchone()[0])
        self.assertEqual(files,list(folder.rglob('*')) if folder.exists() else [])
        self.assertIsNone(receipt(self.conn,self.task['id']))
        saved=deliver(self.conn,self.root,self.data,payload,self.lease)
        self.assertEqual(task_record(self.conn,self.task['id'])['status'],'completed')
        self.assertEqual(deliver(self.conn,self.root,self.data,payload,self.lease)['result_id'],saved['result_id'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_reads WHERE task_id=? AND kind='prepared_bank'",(self.task['id'],)).fetchone()[0],0)
    def test_candidate_out_of_scope_rejected_identically_by_preflight_and_save(self):
        _,scope=self.selection();payload=self.selection_payload(scope);payload['result']['selections'][0]['bank_id']='bank-test'
        errors=[]
        for operation in (preflight,deliver):
            with self.assertRaises(ValueError) as error:operation(self.conn,self.root,self.data,payload,self.lease)
            errors.append(str(error.exception))
        self.assertEqual(errors[0],errors[1]);self.assertIsNone(receipt(self.conn,self.task['id']))
    def test_reserved_exposed_and_original_exam_candidates_are_excluded(self):
        reveal(self.conn,prepared.BANK,'question',True)
        _,scope=self.selection();self.assertEqual(scope['candidates'],{})

    def test_reserved_paper_is_excluded(self):
        save_preferences(self.conn,{'reserved':[{'math_type':2,'year':'2020'}]})
        _,scope=self.selection();self.assertEqual(scope['candidates'],{})

    def test_original_paper_exam_identity_is_excluded_even_without_text_match(self):
        self.conn.execute("UPDATE papers SET title='2020年数二',source_name='2020年数二.pdf' WHERE id='paper-test'")
        _,scope=self.selection();self.assertEqual(scope['candidates'],{})

    def test_candidate_ranking_primary_then_type_then_year_and_limit_five(self):
        from app.bank.annotations import materials
        actual=materials(self.conn,self.data,prepared.BANK)
        self.conn.execute("UPDATE questions SET match_bank_id='bank-test'")
        specifications=[('f',False,'choice',2028),('e',False,'choice',2027),
            ('d',True,'proof',2026),('c',True,'choice',2020),('b',True,'choice',2025),('a',True,'choice',2025)]
        items=[{'id':bid,'annotation_id':self.case.annotation['id'],'year':str(year),
            'bindings':[{'topic_id':prepared.TOPIC,'role':'primary' if primary else 'supporting'}],
            'methods':[],'checkpoints':[],'fingerprint':{},
            'history':{'seen_question':False,'seen_solution':False,'exercises':[]}}
            for bid,primary,typ,year in specifications]
        types={bid:typ for bid,_,typ,_ in specifications};types['bank-test']='choice'
        with patch('app.bank.retrieval.recall',return_value={'items':items,'next_offset':None}), \
             patch('app.learning.selection.metadata',side_effect=lambda conn,bid:{'question_type':types[bid]}), \
             patch('app.learning.selection.annotations.current',return_value=self.case.annotation), \
             patch('app.learning.selection.annotations.materials',return_value=actual), \
             patch('app.learning.practice_knowledge.material_binding',return_value={}):
            _,scope=self.selection()
        self.assertTrue(scope['targets'])
        self.assertEqual(scope['targets'][0]['candidate_ids'],['a','b','c','d','f'])

    def test_missing_reference_roles_fall_back_and_missing_question_is_excluded(self):
        from app.bank.annotations import materials
        from app.bank.retrieval import recall
        from app.learning.selection import capture
        from app.learning.practice_knowledge import material_binding
        _,scope=self.selection();inputs=json.loads(self.task['input_json'])
        items=recall(self.conn,self.data,topic_ids=[prepared.TOPIC],limit=100,internal=True)['items']
        actual=materials(self.conn,self.data,prepared.BANK)
        binding=material_binding(self.conn,self.data,prepared.BANK,self.case.annotation)
        for provided in ({'question':actual['question']},{}, {'analysis':actual['analysis']}):
            with patch('app.bank.retrieval.recall',return_value={'items':items,'next_offset':None}), \
                 patch('app.learning.selection.annotations.current',return_value=self.case.annotation), \
                 patch('app.learning.selection.annotations.materials',return_value=provided), \
                 patch('app.learning.practice_knowledge.material_binding',return_value=binding):
                selected=capture(self.conn,self.data,inputs)
            if 'question' in provided:
                candidate=selected['candidates'][prepared.BANK]
                self.assertEqual(candidate['reference_answer'],self.case.annotation['analysis']['reference_reasoning'])
                self.assertEqual(candidate['reference_analysis'],candidate['reference_answer'])
            else:self.assertEqual(selected['candidates'],{})

    def test_local_delivery_finishes_before_remote_end_and_closes_execution(self):
        b=self.bridge();b.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:b._active() and not b._active()['codex_turn_id'].startswith('pending-'))
        turn=b._active();transport=b.transport
        task=task_record(self.conn,turn['task_id']);self.f.task=task;self.f.kind='summarize_paper'
        qid=self.conn.execute('SELECT id FROM questions LIMIT 1').fetchone()[0]
        value=self.f.envelope({'source_refs':[{'kind':'question','id':qid}],
            'overview':'已保存证据的小结。','key_findings':[],'improvements':[],'unknowns':[],
            'unfinished':[],'next_focus':[]})
        b.event({'method':'item/tool/call','id':'delivery','params':{'threadId':turn['session_id'],
            'turnId':turn['codex_turn_id'],'tool':'mathlens','arguments':{'action':'deliver_result','payload':{'result':value}}}})
        self.assertTrue(transport.sent[-1]['result']['success'],transport.sent[-1])
        self.wait(lambda:not b.finishing)
        self.assertIsNone(b._active());self.assertTrue(transport.closed)
        self.assertEqual(task_record(self.conn,task['id'])['status'],'completed')

    def test_settings_api_returns_real_catalog_and_merges_profiles(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.config import AppConfig
        b=self.bridge()
        config=AppConfig(self.root,self.data,self.root/'dist',server.DB_PATH)
        with TestClient(create_app(config,bridge=b,agent_factory=None,manage_agent=False),base_url='http://127.0.0.1') as http:
            value=http.get('/api/agent/models')
            self.assertEqual(value.status_code,200);self.assertEqual(value.json()['items'][0]['efforts'],['high','xhigh'])
            first=http.post('/api/preferences',json={'reserved':[{'math_type':3,'year':'2026'}],
                'execution_profiles':{'judgment':{'model':'custom-judge','effort':'high'}}})
            self.assertEqual(first.status_code,200,first.text)
            updated=http.post('/api/preferences',json={'execution_profiles':{'organization':{'model':'custom-organizer','effort':'high'}}})
            self.assertEqual(updated.status_code,200,updated.text)
            settings=http.get('/api/preferences').json()
            self.assertEqual(settings['execution_profiles']['judgment']['model'],'custom-judge')
            self.assertEqual(settings['reserved'],[{'math_type':3,'year':'2026'}])
            rejected=http.post('/api/preferences',json={'execution_profiles':{'unexpected':{'model':'x','effort':'y'}}})
            self.assertEqual(rejected.status_code,400)
    def test_model_profiles_and_new_thread_on_each_task(self):
        b=self.bridge()
        save_preferences(self.conn,{'execution_profiles':{'organization':{'model':'gpt-6-luna','effort':'high'}}});self.conn.commit()
        b.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:b._active() and not b._active()['codex_turn_id'].startswith('pending-'))
        first=b.state['session_id'];transport=b.transport
        self.assertEqual(b._active()['model_settings']['effort'],'high')
        b.interrupt();self.wait(lambda:not b.finishing)
        b.connect();self.wait(lambda:b.connected)
        b.submit_task('analyze_paper','paper-test',str(uuid.uuid4()),contract_version='2.0')
        self.wait(lambda:b._active() and not b._active()['codex_turn_id'].startswith('pending-'))
        self.assertNotEqual(first,b.state['session_id']);self.assertEqual(b._active()['model_settings']['effort'],'xhigh')
        self.assertFalse(any(m=='thread/resume' for p in (transport,b.transport) for m,_ in p.calls))

    def test_app_server_can_notify_before_rpc_response_without_deadlock(self):
        import threading
        class EarlyEvent(FakeServer):
            def request(self,method,params):
                result=super().request(method,params)
                if method=='thread/start':
                    worker=threading.Thread(target=lambda:self.notify({'method':'thread/started',
                        'params':{'threadId':result['thread']['id']}}))
                    worker.start();worker.join(timeout=1)
                    if worker.is_alive():raise RuntimeError('bridge lock blocked app-server event')
                return result
        b=CodexBridge(self.root,self.data,EarlyEvent);self.addCleanup(b.close)
        b.connect();self.wait(lambda:b.connected)
        b.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:b._active() and b._active().get('codex_turn_id') and not b._active()['codex_turn_id'].startswith('pending-'))
        self.assertNotIn('pending-session-',b.state['session_id'])

    def test_readonly_execution_uses_empty_external_cwd_and_absolute_images(self):
        from pathlib import Path
        from PIL import Image
        paths=[]
        for folder in ('answer-images','practice-materials','agent-input'):
            target=self.data/folder/'runtime-test.png';target.parent.mkdir(exist_ok=True)
            Image.new('RGB',(12,12),'white').save(target);paths.append(target.resolve())
        case=self
        class CheckedServer(FakeServer):
            def __init__(self,root,*args):
                case.assertFalse(root.is_relative_to(case.root));self.process_cwd=root
                super().__init__(root,*args)
            def request(self,method,params):
                if method in ('thread/start','turn/start'):
                    cwd=Path(params['cwd']);case.assertEqual(cwd,self.process_cwd)
                    case.assertFalse(cwd.is_relative_to(case.root))
                    case.assertEqual([p.name for p in cwd.iterdir()],['AGENTS.md'])
                    case.assertIn('做题龙任务执行器',(cwd/'AGENTS.md').read_text(encoding='utf-8'))
                    case.assertEqual(params['approvalPolicy'],'never')
                    if method=='thread/start':
                        case.assertNotIn('developerInstructions',params)
                        case.assertEqual(params['sandbox'],'read-only')
                        for key in ('skills.include_instructions','skills.bundled.enabled','features.plugins','features.apps'):
                            case.assertIs(params['config'][key],False)
                    else:
                        case.assertEqual(params['sandboxPolicy'],{'type':'readOnly'})
                        supplied=[Path(i['path']) for i in params['input'] if i['type']=='localImage']
                        case.assertEqual(supplied,paths)
                        for image in supplied:
                            case.assertTrue(image.is_absolute());case.assertTrue(image.read_bytes())
                            with Image.open(image) as decoded:case.assertEqual(decoded.size,(12,12))
                return super().request(method,params)
        original=initial_inputs
        def package(*args):return original(*args)+[{'type':'localImage','path':str(p)} for p in paths]
        b=CodexBridge(self.root,self.data,CheckedServer);self.addCleanup(b.close)
        b.connect();self.wait(lambda:b.connected)
        with patch('app.agent.material_package.initial_inputs',side_effect=package):
            b.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))
        self.wait(lambda:b._active() and not b._active()['codex_turn_id'].startswith('pending-'))

    def test_external_workspace_uses_its_own_runtime_directory(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory(prefix='mathlens-runtime-test-') as directory:
            b=CodexBridge(self.root,Path(directory),FakeServer)
            try:
                self.assertEqual(b._runtime_directory(),Path(directory).resolve()/'agent-runtime')
                self.assertEqual([p.name for p in b._runtime_directory().iterdir()],['AGENTS.md'])
            finally:b.close()
    def test_unavailable_model_fails_job_without_fallback(self):
        save_preferences(self.conn,{'execution_profiles':{'organization':{'model':'missing-model','effort':'high'}}});self.conn.commit()
        b=self.bridge();b.queue_task('summarize_paper','paper-test',str(uuid.uuid4()));b._drain_workflows()
        self.wait(lambda:b._workflow_listing()[0]['status']=='failed')
        job=b._workflow_listing()[0];self.assertEqual(job['status'],'failed');self.assertIn('missing-model',job['error'])
        self.assertFalse(any(m=='thread/start' for m,_ in b.transport.calls))
    def test_restart_without_receipt_fails_and_retry_creates_new_execution(self):
        b=self.bridge();b.queue_task('summarize_paper','paper-test',str(uuid.uuid4()));b._drain_workflows()
        self.wait(lambda:b._active() is not None);first=b._active()['task_id'];sid=b.state['session_id']
        job=next(j for j in b._workflow_listing() if j['task_id']==first)
        b.close()
        fresh=self.bridge();self.assertEqual(task_record(self.conn,first)['status'],'failed')
        fresh.workflow_action(job['id'],'retry');fresh._drain_workflows()
        self.wait(lambda:fresh._active() is not None)
        self.assertNotEqual(first,fresh._active()['task_id']);self.assertNotEqual(sid,fresh.state['session_id'])
    def test_restart_with_receipt_does_not_redeliver(self):
        saved=self.save_selection();count=self.conn.execute('SELECT count(*) FROM learning_results').fetchone()[0]
        # Simulate an older result_saved projection at the crash boundary.
        self.conn.execute("UPDATE learning_tasks SET status='result_saved' WHERE id=?",(self.task['id'],));self.conn.commit()
        b=self.bridge()
        self.assertEqual(task_record(self.conn,self.task['id'])['status'],'completed')
        self.assertEqual(receipt(self.conn,self.task['id'])['result_id'],saved['result_id'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_results').fetchone()[0],count)
        self.assertFalse(any(m=='thread/start' for m,_ in b.transport.calls))

    def test_grade_initial_package_saves_in_one_delivery_with_answer_photo(self):
        self._grade_initial_package('own_work')

    def test_grade_initial_package_only_evaluates_marking_when_attached(self):
        self._grade_initial_package('marking')

    def _grade_initial_package(self,role):
        self.save_selection()
        from app.learning.loop import submit_probe
        from app.storage.images import save_answer_image
        from PIL import Image
        from io import BytesIO
        raw=BytesIO();Image.new('RGB',(40,40),'white').save(raw,format='PNG')
        image=save_answer_image(self.conn,self.data,raw.getvalue())
        pid=self.conn.execute('SELECT probe_id FROM practice_question_bindings ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        reveal(self.conn,prepared.BANK,'question',True)
        attempt=submit_probe(self.conn,pid,{'response':r'$2x\cos(x^2)$','image_ids':[image['id']],
            'image_roles':{image['id']:role}})['attempt_id'];self.conn.commit()
        from app.learning.practice_knowledge import bind_attempt
        bind_attempt(self.conn,attempt);self.conn.commit()
        self.f.start('grade_attempt',attempt_id=attempt,contract_version='1.9')
        task=self.f.task;lease=self.f.lease
        package=initial_inputs(self.conn,self.root,self.data,task['id'],lease)
        text=json.loads(package[0]['text'])
        self.assertTrue(text['definitions']);self.assertIn('prompt',text['assignment'])
        self.assertTrue(any(i['type']=='localImage' for i in package))
        self.assertEqual(text['attempt']['image_roles_json'],json.dumps({image['id']:role},ensure_ascii=False))
        requirements='\n'.join(text['requirements'])
        self.assertIn('feedback只写1–3句结论',requirements)
        self.assertIn('无需固定标签',requirements)
        if role=='marking':self.assertIn('本次确实附有事后批改图片',requirements)
        else:self.assertIn('本次未附事后批改图片',requirements)
        value=self.f.envelope({'attempt_id':attempt,'correct':True,'answer_status':'correct',
            'feedback':'结论正确。','reference_reasoning':'外层导数乘内层导数。',
            'observations':[],'first_error':None,'possible_causes':[],'topic_ids':[prepared.TOPIC],
            'next_step':'继续独立检验。','needs_material':[]})
        self.assertTrue(preflight(self.conn,self.root,self.data,value,lease)['valid'])
        saved=deliver(self.conn,self.root,self.data,value,lease)
        self.assertEqual(task_record(self.conn,task['id'])['status'],'completed')
        self.assertIsNotNone(saved['result_id'])

    def review(self,changed=False):
        latest=self.conn.execute('SELECT id FROM agent_reports ORDER BY rowid DESC LIMIT 1').fetchone()[0]
        qid=self.conn.execute("SELECT id FROM questions WHERE number='1'").fetchone()[0]
        self.f.start('review_question',review_request={'question_id':qid,'report_id':latest})
        scope=json.loads(self.f.task['input_json'])['question_review'];q=copy.deepcopy(scope['question'])
        if changed:q['first_error']['evidence']='A different mathematical first error.'
        result={'question':q,'review':{'status':'verified','issues':[]},'completion':'complete',
            'summary':'核对本题，其他证据保留。','priorities':[],
            'resolved_issue_indexes':[],'resolved_limitation_indexes':[]}
        self.case.tool('read_paper',{'paper_id':'paper-test','question_id':qid},self.f.lease)
        task=self.f.task;saved=deliver(self.conn,self.root,self.data,self.f.envelope(result),self.f.lease)
        self.conn.commit();return task_record(self.conn,task['id']),saved

    def test_unchanged_review_adopts_mapping_and_plan_without_followup(self):
        self.save_selection()
        from app.learning.plans import practice_state
        from app.knowledge.mapping_versions import select_sources
        from app.learning.workflows import continue_job
        before=practice_state(self.conn,'paper-test')['probe_ids']
        task,_=self.review(False)
        self.assertEqual(practice_state(self.conn,'paper-test')['probe_ids'],before)
        self.assertFalse([s for s in select_sources(self.conn,'paper-test') if s['kind']=='question'])
        continue_job(self.conn,self.root,self.data,{'id':'test','auto_prepare':1},task)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],0)

    def test_review_inheritance_survives_navigation_snapshot_and_topic_read(self):
        self.save_selection();self.review(False)
        from app.runtime import AppRuntime
        from app.storage.knowledge_reads import navigation_snapshot
        from app.knowledge.index import snapshot
        runtime=AppRuntime(server.config(),agent_factory=None);self.addCleanup(runtime.close)
        expected=snapshot(self.conn)
        with navigation_snapshot(runtime.database) as copied:
            self.assertEqual(snapshot(copied),expected)
        detail=runtime.frontend.topic(prepared.TOPIC)
        self.assertEqual(detail['topic']['id'],prepared.TOPIC)
        self.assertGreater(runtime.knowledge_links.resource_snapshot()['counts'][prepared.TOPIC]['bank'],0)

    def test_changed_review_only_invalidates_dependent_goal(self):
        self.save_selection()
        from app.learning.plans import practice_state
        from app.knowledge.mapping_versions import select_sources
        self.review(True)
        state=practice_state(self.conn,'paper-test')
        self.assertEqual(state['affected_numbers'],['1'])
        # The shared exercise remains usable for its unchanged second target.
        self.assertEqual(len(state['probe_ids']),1)
        pending=[s for s in select_sources(self.conn,'paper-test') if s['kind']=='question']
        self.assertEqual([s['content']['number'] for s in pending],['1'])
        self.case.m.save()
        self.f.start('prepare_practice',contract_version='1.10')
        scope=json.loads(self.f.task['input_json'])['selection']
        self.assertEqual([g['goal']['question_numbers'] for g in scope['targets']],[[1]])
        self.assertEqual(len(scope['retained_exercises']),1)
