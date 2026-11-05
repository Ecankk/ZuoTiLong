import copy,json,sqlite3,unittest,uuid
from contextlib import closing
from unittest.mock import patch
import test_learning_loop as fixtures
import test_learning_tasks as task_fixtures
import test_frontend_tasks as frontend_fixtures
import database_fixture as server
from app.config import AppConfig
from app.learning.loop import apply_report
from app.learning.contracts import validate_result
from app.storage.restore_regions import restore


class AnalysisQualityTests(unittest.TestCase):
    def setUp(self):
        self.f=task_fixtures.LearningTaskTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn=self.f.conn;self.data=self.f.data
        self.config=AppConfig(server.ROOT,self.data,server.DIST,server.DB_PATH)

    def test_local_regions_survive_report_and_new_question_gets_location_notice(self):
        precise=[dict(page=1,bbox=[20,40,560,200],role='question_and_work')]
        self.conn.execute('INSERT INTO questions(id,paper_id,number,regions_json,created_at) VALUES(?,?,?,?,?)',('stable','paper-test','1',json.dumps(precise),'now'))
        report=copy.deepcopy(self.f.fixture.report);report['probes']=[]
        for q in report['questions']:q['regions']=[dict(page=1,bbox=[0,0,595,842],role='question_and_work')]
        result=apply_report(self.conn,'paper-test',report,self.f.root)
        self.assertEqual(json.loads(self.conn.execute("SELECT regions_json FROM questions WHERE id='stable'").fetchone()[0]),precise)
        new=self.conn.execute("SELECT * FROM questions WHERE number='2'").fetchone()
        self.assertEqual(json.loads(new['regions_json'])[0]['bbox'],[0,0,595,842])
        saved=json.loads(self.conn.execute('SELECT report_json FROM agent_reports WHERE id=?',(result['report_id'],)).fetchone()[0])
        self.assertEqual(saved['questions'][0]['regions'],precise);self.assertIn('位置待确认',saved['questions'][1]['observation'])
        self.assertEqual(apply_report(self.conn,'paper-test',report,self.f.root)['report_id'],result['report_id'])

    def test_restore_from_cache_is_previewed_backed_up_and_keeps_missing_number(self):
        from app.documents.pdf import PIPELINE_VERSION
        folder=self.data/'ocr-cache'/self.f.fixture.digest;folder.mkdir(parents=True)
        pages=[dict(page_number=1,width=595,height=842,blocks=[dict(text=f'({n}) question',bbox=[50,y,450,y+20]) for n,y in ((1,50),(3,250),(4,450))])]
        (folder/f'{PIPELINE_VERSION}-ocr.json').write_text(json.dumps(dict(pages=pages)),encoding='utf8')
        for n in range(1,5):self.conn.execute('INSERT INTO questions(id,paper_id,number,regions_json,created_at) VALUES(?,?,?,?,?)',(f'q{n}','paper-test',str(n),'[{"page":1,"bbox":[0,0,595,842]}]','now'))
        self.conn.commit()
        with patch('app.documents.pdf._ocr_blocks',side_effect=AssertionError('OCR')):
            plan=restore(self.config,'paper-test');self.assertEqual({x['number'] for x in plan['missing']},{'2'})
            self.assertEqual({x['number'] for x in plan['changed']},{'1','3','4'})
            self.assertFalse((self.data/'backups').exists())
            with self.assertRaises(ValueError):restore(self.config,'paper-test','bad')
            result=restore(self.config,'paper-test',plan['plan_sha256'])
        self.assertTrue(result['applied'])
        with closing(sqlite3.connect(result['backup'])) as old:self.assertEqual(json.loads(old.execute("SELECT regions_json FROM questions WHERE id='q1'").fetchone()[0])[0]['bbox'],[0,0,595,842])
        self.assertEqual(json.loads(self.conn.execute("SELECT regions_json FROM questions WHERE id='q2'").fetchone()[0])[0]['bbox'],[0,0,595,842])
        self.assertFalse(restore(self.config,'paper-test')['changed'])

    def test_analysis_reports_all_semantic_errors_with_numbers(self):
        self.f.start();payload=self.f.analysis();payload['result']['report']['expected_count']=3
        q1,q2=payload['result']['report']['questions']
        q1['answer_evidence']['student_work']='';q1['regions']=[]
        q2['correctness']='correct';q2['first_error']=dict(stage='calculation',step='bad',evidence='bad');q2['reference_reasoning']=''
        with self.assertRaises(ValueError) as caught:validate_result(payload,'analyze_paper')
        error=str(caught.exception)
        self.assertIn('缺失题号=[3]',error);self.assertIn('第1题：原作答可辨',error)
        self.assertIn('第1题：仅缺失证据',error);self.assertIn('第2题：有实质性步骤',error);self.assertIn('第2题：判定作答前',error)

    def test_initial_analysis_has_references_coverage_images_and_honest_receipts(self):
        self.conn.execute("UPDATE papers SET title='2021 数学一' WHERE id='paper-test'")
        self.conn.execute("UPDATE bank_identity SET year='2021',math_type=1,number=2 WHERE bank_id='bank-test'")
        self.conn.execute("UPDATE bank_questions SET answer='B',explanation='reference reasoning' WHERE id='bank-test'")
        self.conn.execute("UPDATE bank_resources SET question_path='' WHERE bank_id='bank-test'")
        self.conn.execute("INSERT INTO questions(id,paper_id,number,regions_json,created_at) VALUES('q1','paper-test','1','[]','now')");self.conn.commit()
        self.f.start()
        from app.agent.material_package import initial_inputs
        packet=initial_inputs(self.conn,self.f.root,self.data,self.f.task['id'],self.f.lease)
        header=json.loads(packet[0]['text']);self.assertEqual(header['expected_count'],2);self.assertEqual(header['missing_question_numbers'],[2])
        self.assertTrue(header['materials_complete']);self.assertTrue(any(c['type']=='localImage' for c in packet))
        reference=header['analysis_references'][0]
        self.assertEqual(reference['number'],2);self.assertEqual(next(r['text'] for r in reference['resources'] if r['role']=='answer'),'B')
        self.assertTrue({'paper','analysis_reference'}.issubset({r['kind'] for r in header['read_receipts']}))
        payload=self.f.analysis();q=payload['result']['report']['questions'][1]
        q['correctness']='unknown';q['first_error']=None;q['answer_evidence']['marking']='none'
        context=json.loads(self.f.task['input_json'])['analysis_materials']
        with self.assertRaisesRegex(ValueError,'第2题：作答可辨且已提供参考'):validate_result(payload,'analyze_paper',analysis_context=context)


class AttentionTests(unittest.TestCase):
    def test_later_success_resolves_old_failure_but_preserves_database_history(self):
        from app.runtime import AppRuntime
        f=task_fixtures.LearningTaskTests();f.setUp();self.addCleanup(f.tearDown)
        from app.learning.workflows import enqueue
        a=enqueue(f.conn,f.root,f.data,'analyze_paper','paper-test',str(uuid.uuid4()))
        f.conn.execute("UPDATE workflow_jobs SET status='failed',error='old failure' WHERE id=?",(a['id'],))
        b=enqueue(f.conn,f.root,f.data,'analyze_paper','paper-test',str(uuid.uuid4()))
        f.conn.execute("UPDATE workflow_jobs SET status='completed' WHERE id=?",(b['id'],));f.conn.commit()
        rt=AppRuntime(AppConfig(f.root,f.data,server.DIST,server.DB_PATH),agent_factory=None);self.addCleanup(rt.close)
        value=rt.tasks.read();self.assertEqual(value['failed_count'],0);self.assertNotIn(a['id'],{j['id'] for j in value['items']})
        self.assertEqual(f.conn.execute('SELECT status FROM workflow_jobs WHERE id=?',(a['id'],)).fetchone()[0],'failed')
