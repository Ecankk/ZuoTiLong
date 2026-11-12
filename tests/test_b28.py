import copy,json,unittest,uuid
from datetime import date,datetime,timedelta,timezone
from unittest.mock import patch
import test_f5_backend as fixtures
from app.learning import dates
from app.knowledge.profile import aggregate

class DateRuleTests(unittest.TestCase):
    def test_loss_sort_precedes_unscored_practice_count(self):
        from app.services.profile_metrics import weak_spots
        clock=datetime.now(timezone.utc)
        def fact(id,points,source='exam'):
            return dict(id=id,question_id=id,correct=False,independent=None,source=source,occurred_at=clock.date().isoformat(),lost_points=points,label='Synthetic',first_error=None)
        nodes={id:dict(id=id,name=id,kind='chapter',parent_id=None,distribution={'weak':1}) for id in ('a','b')}
        d=dict(clock=clock,nodes=nodes,descendants={'a':set(),'b':set()},node_facts=dict(a=[fact('a',6)]+[fact('p'+str(i),None,'practice') for i in range(20)],b=[fact('b',9)]))
        result=weak_spots(d);self.assertEqual([r['node_id'] for r in result],['b','a'])
        self.assertEqual(result[0]['recent_lost_points'],9);self.assertEqual(result[1]['recent_practice_failure_count'],20)
    def test_saved_loss_and_global_first_error_threshold(self):
        from app.services.profile_metrics import loss,first_error_summary
        self.assertEqual(loss(dict(max_score=10,score_earned=4,correctness='partial'),{})['lost_points'],6)
        self.assertIsNone(loss(dict(max_score=0,score_earned=0),{})['lost_points'])
        self.assertIsNone(loss(dict(max_score=10,score_earned=None),{})['lost_points'])
        self.assertEqual(loss(dict(max_score=10,score_earned=10,correctness='wrong'),{})['loss_unavailable_reason'],'score_conflict')
        clock=datetime.now(timezone.utc)
        facts=[dict(id=str(i),source='exam',question_id=str(i),question_number=str(i+1),paper_id='p',practice_source=None,practice_id=None,attempt_id=None,bank_id=None,batch_id=None,label='Synthetic',occurred_at=clock.date().isoformat(),correct=False,independent=None,first_error=dict(stage='calculation',evidence='保存的漏乘步骤')) for i in range(5)]
        d=dict(clock=clock,facts=facts);summary=first_error_summary(d)
        self.assertEqual(summary['dominant_count'],5);self.assertEqual(summary['wrong_count'],5)
        self.assertEqual(summary['evidence'][0]['label'],facts[0]['label'])
        self.assertIn('from',summary['window']);self.assertIsNone(first_error_summary(dict(d,facts=facts[:4])))
        for f in facts:f['occurred_at']=None
        self.assertIsNone(first_error_summary(d))
    def test_precision_validation_and_interval_order(self):
        self.assertEqual(dates.normalize()['exam_date'],None)
        self.assertEqual(dates.normalize(None,'unknown','forgotten')['exam_date_unknown_reason'],'forgotten')
        self.assertEqual(dates.normalize('2026-01')['exam_date_precision'],'month')
        for v in ('2026-13','2026-02-30','20260101','2999-01-01'):
            with self.assertRaises(ValueError):dates.normalize(v)
        with self.assertRaises(ValueError):dates.normalize('2026-01','day')
        self.assertEqual(len(dates.groups([dict(id='a',created_at='2026-01'),dict(id='b',created_at='2026-01-28'),dict(id='c',created_at='')])),2)

    def test_same_day_unknown_and_overlapping_month_conflicts_are_learning(self):
        for times in [('2026-01-02','2026-01-02T23:59:00'),('',''),('2026-01','2026-01-24')]:
            events=[dict(id=str(i),kind=k,created_at=t,source='exam',question_id=str(i),paper_id=str(i),verified=True) for i,(k,t) in enumerate(zip(('exam_success','exam_error'),times))]
            for ordered in (events,list(reversed(events))):
                item=dict(events=copy.deepcopy(ordered),question_ids=[],probe_ids=[],scopes=[],scope_level='concept')
                aggregate(item);self.assertEqual(item['state'],'巩固中');self.assertEqual(item['failures'],1)
        item['events'].append(dict(id='later',source='exam',question_id='later',paper_id='p',kind='exam_error',created_at='2026-02-20',verified=True))
        aggregate(item);self.assertEqual(item['state'],'需要关注')

class PaperMetadataTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.F5BackendTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.app,self.http=self.f.client();self.conn=self.f.f.conn
    def pdf(self,text):
        import pymupdf
        with pymupdf.open() as d:d.new_page().insert_text((30,30),text);return d.tobytes()
    def upload(self,content,title='2021年数一',**fields):
        with patch.object(self.app.state.runtime.papers,'analyze',side_effect=RuntimeError('synthetic local scan')):
            return self.http.post('/api/papers/import',data=dict(title=title,**fields),files={'file':('2021-math1.pdf',content,'application/pdf')})
    def test_unknown_month_bulk_dates_and_transaction_receipts(self):
        first=self.upload(self.pdf('one'));self.assertEqual(first.status_code,201,first.text)
        p=first.json()['paper'];self.assertIsNone(p['exam_date']);self.assertEqual(p['exam_date_precision'],'unknown')
        month=self.http.post('/api/papers',json=dict(title='history',exam_date='2026-01')).json()['paper'];self.assertEqual(month['exam_date_precision'],'month')
        body=dict(confirmed=True,request_id=str(uuid.uuid4()),paper_ids=[p['id'],month['id']],exam_date=None,exam_date_precision='unknown',exam_date_unknown_reason='forgotten')
        r=self.http.post('/api/papers/dates',json=body);self.assertEqual(r.status_code,200,r.text)
        self.assertTrue(self.http.post('/api/papers/dates',json=body).json()['reused'])
        self.assertEqual(self.http.post('/api/papers/dates',json=dict(body,exam_date='2026-01',exam_date_precision='month',exam_date_unknown_reason=None)).status_code,409)
        self.assertEqual(self.http.post('/api/papers/dates',json=dict(body,request_id=str(uuid.uuid4()),paper_ids=[p['id'],'missing'])).status_code,404)
        self.assertIsNone(self.http.get('/api/papers/'+p['id']).json()['paper']['exam_date'])

    def test_duplicate_decision_withdraw_retake_and_sha_reuse(self):
        a=self.pdf('first');b=self.pdf('second');first=self.upload(a).json();second=self.upload(b)
        self.assertEqual(second.status_code,201,second.text);second=second.json();self.assertEqual(second['import_decision'],'pending_duplicate')
        pid=second['paper']['id'];self.assertEqual(second['duplicate_check']['matches'][0]['paper_id'],first['paper']['id'])
        self.assertEqual(self.http.post('/api/papers/'+pid+'/analyze',json={'confirmed':True}).status_code,409)
        self.assertEqual(self.upload(b).json()['paper']['id'],pid)
        body=dict(confirmed=True,request_id=str(uuid.uuid4()),decision='withdraw',decision_revision=second['decision_revision'])
        r=self.http.post('/api/papers/'+pid+'/import-decision',json=body);self.assertEqual(r.status_code,200,r.text)
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('math1-2021-01','Synthetic','Synthetic','now')")
        self.conn.execute("INSERT INTO bank_identity VALUES('math1-2021-01',1,'2021',1,NULL)");self.conn.commit()
        from app.bank.originals import uploaded_originals
        self.assertEqual(uploaded_originals(self.conn)['math1-2021-01'],[first['paper']['id']])
        self.assertTrue(self.http.post('/api/papers/'+pid+'/import-decision',json=body).json()['reused'])
        self.assertEqual(self.http.post('/api/papers/'+pid+'/restore',json={'confirmed':True}).status_code,409)
        detail=self.http.get('/api/papers/'+pid).json()
        retained=self.http.post('/api/papers/'+pid+'/import-decision',json=dict(body,request_id=str(uuid.uuid4()),decision='retake',decision_revision=detail['decision_revision']))
        self.assertEqual(retained.status_code,200,retained.text);self.assertEqual(retained.json()['import_decision'],'accepted')
        self.assertEqual(self.upload(a).json()['duplicate_check']['status'],'same_pdf')

    def test_date_only_correction_keeps_saved_mapping_and_task_payload_bytes(self):
        import test_execution_v2 as execution
        from app.services.paper_metadata import PaperMetadata
        import database_fixture as server
        f=execution.ExecutionTests();f.setUp();self.addCleanup(f.doCleanups)
        old=[tuple(r) for r in f.conn.execute('SELECT id,input_json,input_revision FROM learning_tasks')]
        from app.knowledge import index,mapping_versions
        before=index.sources(f.conn,'paper-test');self.assertTrue(before)
        from app.storage.database import Database
        service=PaperMetadata(server.config(),Database(server.config()))
        response=service.dates(dict(confirmed=True,request_id=str(uuid.uuid4()),paper_ids=['paper-test'],exam_date='2025-01',exam_date_precision='month',exam_date_unknown_reason=None))
        self.assertEqual(response['updated'][0]['exam_date'],'2025-01')
        self.assertEqual(old,[tuple(r) for r in f.conn.execute('SELECT id,input_json,input_revision FROM learning_tasks')])
        current=index.sources(f.conn,'paper-test');mapped=mapping_versions.latest(f.conn,index.catalog(f.conn))
        for s in current:
            if s['kind']=='question':self.assertEqual(mapped[(s['source_id'],s['source_revision'])]['status'],'current')
        from app.main import create_app
        from fastapi.testclient import TestClient
        with TestClient(create_app(server.config(),agent_factory=None),base_url='http://127.0.0.1') as http:
            overview=http.get('/api/profile/overview');self.assertEqual(overview.status_code,200,overview.text)
            self.assertTrue(overview.json()['weak_spots_context']['uses_history_fallback'])
            self.assertEqual(overview.json()['weak_spots'][0]['evidence_period'],'historical')
            self.assertEqual(overview.json()['weak_spots'][0]['recent_failures'],0)
            self.assertIsNone(overview.json()['first_error_summary'])
            self.assertEqual(http.get('/api/profile/trends').json()['unplaced_by_precision']['month']['attempts'],2)
