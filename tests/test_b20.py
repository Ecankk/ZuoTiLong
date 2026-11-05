import copy,json,sqlite3,unittest,uuid
from io import BytesIO
from unittest.mock import patch
from PIL import Image
import database_fixture as server
import test_f5_backend as f5
import test_task_bridge as bridge_tests
import test_free_practice as free_tests


class SplitTests(unittest.TestCase):
    def setUp(self):
        self.f=f5.F5BackendTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.app,self.http=self.f.client();self.conn=self.f.f.conn
        # One old question spans two numbered questions, and two other fragments.
        for i in range(1,4):
            self.conn.execute('INSERT INTO questions(id,paper_id,number,stem,correctness,regions_json,created_at) VALUES(?,?,?,?,?,?,?)',
                ('q'+str(i),'paper-test',str(i),'original text','unknown',json.dumps([dict(page=1,bbox=[20,30,500,400])]),'now'))
        self.conn.commit()
        self.body=dict(confirmed=True,questions=[dict(number='1',question_ids=['q1'],split=dict(page=1,y=200.25,lower_number='2')),
            dict(number='3',question_ids=['q2','q3'])],delete_question_ids=[])

    def test_split_merge_exact_coordinates_original_id_and_fallback_text(self):
        before=self.http.get('/api/questions/q1').json()['evidence_regions'][0]
        image=self.http.get(before['image_url'])
        with Image.open(BytesIO(image.content)) as im:self.assertEqual(list(im.size),[before['image_width'],before['image_height']])
        self.assertEqual(before['image_origin'],[40,60]);self.assertEqual(before['scale'],2)
        result=self.http.post('/api/papers/paper-test/questions/correct',json=self.body)
        self.assertEqual(result.status_code,200,result.text)
        qs={q['number']:dict(q) for q in self.conn.execute('SELECT * FROM questions')}
        self.assertEqual(set(qs),{'1','2','3'});self.assertEqual(qs['1']['id'],'q1')
        self.assertEqual(json.loads(qs['1']['regions_json'])[0]['bbox'],[20,30,500,200.25])
        self.assertEqual(json.loads(qs['2']['regions_json'])[0]['bbox'],[20,200.25,500,400])
        self.assertEqual(qs['1']['stem'],'original text');self.assertEqual(qs['2']['stem'],'待补充题干')
        self.assertEqual(self.conn.execute("SELECT count(*) FROM record_versions WHERE kind='question_segmentation'").fetchone()[0],1)
        self.assertNotEqual(qs['2']['id'],'q1')
        with patch('app.services.papers.match_bank_questions',wraps=__import__('app.documents.pdf',fromlist=['match_bank_questions']).match_bank_questions) as matcher:
            self.f.service.analyze(self.conn,'paper-test');self.assertTrue(matcher.called)

    def test_positioned_ocr_split_and_out_of_bounds_atomic_failure(self):
        from app.documents.pdf import PIPELINE_VERSION
        folder=server.DATA/'ocr-cache'/self.f.f.digest;folder.mkdir(parents=True)
        (folder/f'{PIPELINE_VERSION}-ocr.json').write_text(json.dumps({'pages':[{'page_number':1,'blocks':[
            {'text':'upper','bbox':[30,50,400,70]},{'text':'lower','bbox':[30,250,400,270]}]}]}),encoding='utf8')
        bad=copy.deepcopy(self.body);bad['questions'][0]['split']['y']=999
        self.assertEqual(self.http.post('/api/papers/paper-test/questions/correct',json=bad).status_code,400)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM record_versions').fetchone()[0],0)
        self.assertEqual(self.http.post('/api/papers/paper-test/questions/correct',json=self.body).status_code,200)
        texts={r['number']:r['stem'] for r in self.conn.execute('SELECT * FROM questions')}
        self.assertEqual(texts['1'],'upper');self.assertEqual(texts['2'],'lower')

    def test_history_rejected_and_cross_page_region_partition(self):
        self.conn.execute("INSERT INTO agent_reports VALUES('old','paper-test',?,'{}','now')",(self.f.f.digest,))
        self.conn.execute("INSERT INTO question_diagnoses VALUES('q1','old','{}')");self.conn.commit()
        self.assertEqual(self.http.post('/api/papers/paper-test/questions/correct',json=self.body).status_code,409)
        from app.documents.split_question import split
        q=dict(stem='old',regions_json=json.dumps([dict(page=1,bbox=[0,20,100,100]),dict(page=2,bbox=[0,10,100,200]),dict(page=3,bbox=[0,20,100,100])]))
        up,down,_=split(q,dict(page=2,y=100),server.DATA,'none')
        self.assertEqual([r['page'] for r in up],[1,2]);self.assertEqual([r['page'] for r in down],[2,3])


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.f=bridge_tests.TaskBridgeTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_last_rejection_survives_undelivered_task_and_job(self):
        b=self.f.bridge
        rid=str(uuid.uuid4());b.queue_task('analyze_paper','paper-test',rid)
        self.f.wait(lambda:b._active() and b._active()['codex_turn_id'] and not b._active()['codex_turn_id'].startswith('pending-'))
        turn=b._active();tid=turn['task_id']
        with patch('app.agent.tools.execute',side_effect=ValueError('result/question/2 缺少解法')):
            response,message=self.f.call('deliver_result',{'result':{}})
        self.assertFalse(response['success']);self.assertIn('缺少解法',message)
        self.f.end();self.f.wait(lambda:not b.finishing)
        conn=self.f.fixture.conn
        self.assertIn('缺少解法',conn.execute('SELECT error FROM learning_tasks WHERE id=?',(tid,)).fetchone()[0])
        self.assertIn('缺少解法',conn.execute('SELECT error FROM workflow_jobs WHERE request_id=?',(rid,)).fetchone()[0])

    def test_internal_error_is_logged_and_stops_without_blind_retry(self):
        turn=self.f.start()
        with patch('app.agent.tools.execute',side_effect=sqlite3.IntegrityError('UNIQUE constraint failed: questions.id')),self.assertLogs('app.agent.bridge',level='ERROR') as logs:
            response,message=self.f.call('deliver_result',{'result':{}})
        self.assertFalse(response['success']);self.assertIn('请勿重复提交',message);self.assertIn('Traceback','\n'.join(logs.output))
        self.f.wait(lambda:not self.f.bridge.finishing)
        self.assertIsNone(self.f.bridge._active());self.assertIn('questions.id',turn['error'])

    def test_missing_source_hash_is_completed_and_mismatch_still_rejected(self):
        turn=self.f.start();f=self.f.fixture
        from app.learning.tasks import task_record
        f.kind='analyze_paper';f.task=task_record(f.conn,turn['task_id'])
        self.f.call('read_paper',{'paper_id':'paper-test','pages':[1]})
        payload=f.analysis();payload['result']['report']['source_sha256']='f'*64
        response,message=self.f.call('deliver_result',{'result':payload});self.assertFalse(response['success'])
        payload['result']['report'].pop('source_sha256')
        response,value=self.f.call('deliver_result',{'result':payload});self.assertTrue(response['success'],value)
        saved=json.loads(f.conn.execute('SELECT payload_json FROM learning_results WHERE task_id=?',(turn['task_id'],)).fetchone()[0])
        self.assertEqual(saved['result']['report']['source_sha256'],f.fixture.digest)

    def test_first_paper_and_bank_calls_have_separate_decodable_images(self):
        from app.storage.boundaries import library_root
        folder=library_root(self.f.fixture.data)/'bank-assets';folder.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(20,20),'white').save(folder/'q.png')
        self.f.fixture.conn.execute("UPDATE bank_resources SET question_path='bank-assets/q.png' WHERE bank_id='bank-test'");self.f.fixture.conn.commit()
        self.f.start()
        for action,payload in [('read_paper',{'paper_id':'paper-test','pages':[1]}),('read_bank',{'bank_id':'bank-test','role':'question'})]:
            response,_=self.f.call(action,payload)
            self.assertTrue(response['success'],response);images=[i for i in response['contentItems'] if i['type']=='inputImage'];self.assertTrue(images)
            self.assertTrue(all('base64,' not in i['text'] for i in response['contentItems'] if i['type']=='inputText'))
            import base64
            for item in images:
                with Image.open(BytesIO(base64.b64decode(item['imageUrl'].split(',',1)[1]))) as image:self.assertGreater(image.width,0)


class FreeViewTests(unittest.TestCase):
    def test_first_get_is_read_only_and_legacy_image_labels_are_null(self):
        f=free_tests.FreePracticeTests();f.setUp();self.addCleanup(f.doCleanups)
        # Use the fixture's resolved library owner, rather than an assumed layout.
        from app.storage.boundaries import library_root
        folder=library_root(server.DATA)/'bank-assets';folder.mkdir(parents=True,exist_ok=True)
        Image.new('RGB',(20,20),'white').save(folder/'q.png')
        f.conn.execute("UPDATE bank_resources SET question_path='bank-assets/q.png',analysis_path='bank-assets/q.png' WHERE bank_id='bank-test'")
        f.conn.execute("UPDATE bank_questions SET stem='2025 数学二 第1题 · 偏导数的概念与计算',explanation='参考解析见原图' WHERE id='bank-test'");f.conn.commit()
        before={p.relative_to(server.DATA) for p in server.DATA.rglob('*')};changes=f.conn.total_changes
        with patch('app.storage.practice_materials.freeze',side_effect=AssertionError('GET froze snapshot')):
            value=f.http.get(f.url);self.assertEqual(value.status_code,200,value.text)
        self.assertIsNone(value.json()['question']['question_text']);self.assertEqual(before,{p.relative_to(server.DATA) for p in server.DATA.rglob('*')})
        self.assertEqual(f.conn.total_changes,changes)
        f.http.post('/api/bank/bank-test/reveal',json={'confirmed':True,'role':'analysis'})
        self.assertIsNone(f.http.get(f.url).json()['reference']['analysis_text'])
        result=f.submit(choice='B');self.assertEqual(result.status_code,200,result.text)
        self.assertIsNone(result.json()['materials']['question']['question_text'])
        self.assertTrue((server.DATA/'practice-materials').is_dir())
