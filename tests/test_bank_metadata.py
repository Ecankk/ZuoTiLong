from app.storage.boundaries import library_root
import hashlib
import json
from pathlib import Path
import sqlite3
import unittest
import uuid
from PIL import Image
from fastapi.testclient import TestClient

from app.bank import annotations,metadata
from app.knowledge.catalog import digest
from app.learning.loop import import_image_bank
from app.learning.tasks import finish_task
from app.main import create_app
from app.services.library import LibraryService
from app.storage.database import Database


class BankNavigationTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.f.prepare_catalog();self.conn=self.f.conn;self.data=self.f.data;self.config=self.f.f.config
        self.db=Database(self.config);self.bid='math1-2020-01';self.source=self.data/'image-source'
        self.group=self.source/'kaoyan_math_images'/'数学一';self.folder=self.group/'2020'
        (self.folder/'analysis').mkdir(parents=True);(self.folder/'answers').mkdir()
        self.q={'paper':'2020','index':1,'question_id':7,'knowledge_point':'向量正交','answer':None}
        (self.group/'answers.json').write_text(json.dumps({'test':self.q},ensure_ascii=False),encoding='utf-8')
        self.source_paths={'question':self.folder/'Q01_id7.png','analysis':self.folder/'analysis/Q01_id7_analysis.png',
                           'answer':self.folder/'answers/Q01_id7_answer.png'}
        for i,p in enumerate(self.source_paths.values()):Image.new('RGB',(80,50),(30+i*25,80,130)).save(p)
        import_image_bank(self.conn,self.source,self.data,math_types=(1,));self.conn.commit()
        self.body={'confirmed':True,'request_id':str(uuid.uuid4()),'expected_material_revision':digest(annotations.materials(self.conn,self.data,self.bid)),
                   'topic':'复合函数的链式求导','reason':'核查隔离题图与参考后，原生成导航分类与本题数学内容不符。'}
        self.service=LibraryService(self.config,self.db)

    def state(self):
        return {'question':tuple(self.conn.execute('SELECT * FROM bank_questions WHERE id=?',(self.bid,)).fetchone()),
                'resource':tuple(self.conn.execute('SELECT * FROM bank_resources WHERE bank_id=?',(self.bid,)).fetchone()),
                'identity':tuple(self.conn.execute('SELECT * FROM bank_identity WHERE bank_id=?',(self.bid,)).fetchone()),
                'images':{r:hashlib.sha256((library_root(self.data)/'bank-assets'/self.bid/(r+'.png')).read_bytes()).hexdigest() for r in self.source_paths},
                'history':self.conn.execute('SELECT count(*) FROM bank_metadata_revisions').fetchone()[0]}

    def test_confirmed_http_correction_keeps_original_history_materials_identity_and_student_records(self):
        before=self.state()
        with TestClient(create_app(self.config,agent_factory=None),base_url='http://127.0.0.1') as client:
            response=client.post('/api/bank/'+self.bid+'/navigation',json=self.body)
            self.assertEqual(response.status_code,200,response.text)
            result=response.json();self.assertTrue(result['requires_annotation_review'])
        after=self.state();self.assertEqual(after['images'],before['images']);self.assertEqual(after['identity'],before['identity'])
        saved=self.conn.execute('SELECT * FROM bank_metadata_revisions').fetchone()
        self.assertEqual(json.loads(saved['before_json'])['stem'],before['question'][3])
        self.assertEqual(self.conn.execute('SELECT stem FROM bank_questions WHERE id=?',(self.bid,)).fetchone()[0],'2020 数学一 第1题 · 复合函数的链式求导')
        self.assertNotEqual(result['before_revision'],result['after_revision'])
        self.assertEqual(result['after_revision'],digest(annotations.materials(self.conn,self.data,self.bid)))
        for table in ['probe_attempts','learning_events','bank_views','bank_exposures']:
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_stale_material_or_missing_confirmation_does_not_write(self):
        before=self.state()
        for changes in [{'confirmed':False},{'expected_material_revision':'0'*64}]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.service.correct_navigation(self.bid,{**self.body,**changes})
            self.assertEqual(self.state(),before)
        with TestClient(create_app(self.config,agent_factory=None),base_url='http://127.0.0.1') as client:
            self.assertEqual(client.post('/api/bank/'+self.bid+'/navigation',json={**self.body,'confirmed':'true'}).status_code,400)

    def test_idempotent_retry_cannot_replace_a_later_correction_or_change_its_payload(self):
        first=self.service.correct_navigation(self.bid,self.body)
        retry=self.service.correct_navigation(self.bid,self.body);self.assertTrue(retry['reused']);self.assertTrue(retry['still_current'])
        second={**self.body,'request_id':str(uuid.uuid4()),'expected_material_revision':first['after_revision'],'topic':'一元复合函数求导'}
        latest=self.service.correct_navigation(self.bid,second)
        replay=self.service.correct_navigation(self.bid,self.body);self.assertTrue(replay['reused']);self.assertFalse(replay['still_current'])
        self.assertEqual(digest(annotations.materials(self.conn,self.data,self.bid)),latest['after_revision'])
        with self.assertRaisesRegex(ValueError,'同一校正请求'):self.service.correct_navigation(self.bid,{**self.body,'topic':'其他'})
        self.assertEqual(self.state()['history'],2)

    def test_actual_text_stem_is_not_editable_and_curated_fingerprint_is_not_overwritten(self):
        self.conn.execute('UPDATE bank_questions SET stem=? WHERE id=?',('这是实际题干，不能按导航改写。',self.bid));self.conn.commit()
        body={**self.body,'expected_material_revision':digest(annotations.materials(self.conn,self.data,self.bid))};before=self.state()
        with self.assertRaisesRegex(ValueError,'实际题干'):self.service.correct_navigation(self.bid,body)
        self.assertEqual(self.state(),before)
        fingerprint={'methods':['chain rule'],'operations':['differentiate composition']}
        self.conn.execute('UPDATE bank_questions SET stem=?,fingerprint_json=? WHERE id=?',('2020 数学一 第1题 · 向量正交',json.dumps(fingerprint),self.bid));self.conn.commit()
        self.service.correct_navigation(self.bid,{**self.body,'expected_material_revision':digest(annotations.materials(self.conn,self.data,self.bid))})
        self.assertEqual(json.loads(self.conn.execute('SELECT fingerprint_json FROM bank_questions WHERE id=?',(self.bid,)).fetchone()[0]),fingerprint)

    def test_failure_after_resource_update_rolls_back_labels_and_history(self):
        self.conn.execute("CREATE TRIGGER library.reject_nav_history BEFORE INSERT ON bank_metadata_revisions BEGIN SELECT RAISE(ABORT,'injected write failure'); END");self.conn.commit()
        before=self.state()
        with self.assertRaises(sqlite3.IntegrityError):self.service.correct_navigation(self.bid,self.body)
        self.assertEqual(self.state(),before)

    def test_same_source_reimport_preserves_correction_and_changed_reference_is_rejected_before_copy(self):
        self.service.correct_navigation(self.bid,self.body);before=self.state()
        value=import_image_bank(self.conn,self.source,self.data,math_types=(1,));self.conn.commit()
        self.assertEqual(value['preserved_navigation'],[self.bid]);self.assertEqual(self.state(),before)
        (self.group/'answers.json').write_text(json.dumps({'test':{**self.q,'answer':'changed reference text'}},ensure_ascii=False),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'参考正文版本变化'):import_image_bank(self.conn,self.source,self.data,math_types=(1,))
        self.conn.rollback();self.assertEqual(self.state(),before)
        (self.group/'answers.json').write_text(json.dumps({'test':self.q},ensure_ascii=False),encoding='utf-8')
        Image.new('RGB',(80,50),(255,0,0)).save(self.source_paths['analysis'])
        with self.assertRaisesRegex(ValueError,'参考版本变化'):import_image_bank(self.conn,self.source,self.data,math_types=(1,))
        self.conn.rollback();self.assertEqual(self.state(),before)

    def test_busy_application_rejects_correction(self):
        from test_fastapi_app import OwnedAgent
        agent=OwnedAgent(self.config.root,self.data);agent.busy=True;before=self.state()
        with TestClient(create_app(self.config,bridge=agent,agent_factory=None,manage_agent=False),base_url='http://127.0.0.1') as client:
            response=client.post('/api/bank/'+self.bid+'/navigation',json=self.body)
            self.assertEqual(response.status_code,409,response.text)
        self.assertEqual(self.state(),before)

    def test_correction_invalidates_old_ready_without_deleting_annotation_or_fabricating_new_receipt(self):
        self.f.start('annotate_questions',{'bank_ids':[self.bid]});self.f.read_annotation_material()
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())});finish_task(self.conn,self.f.task['id']);self.conn.commit()
        old=annotations.current(self.conn,self.data,self.bid);self.assertIsNotNone(old)
        counts={t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ['question_annotations','learning_tasks','learning_results','task_reads']}
        self.service.correct_navigation(self.bid,self.body)
        self.assertIsNone(annotations.current(self.conn,self.data,self.bid))
        for table,count in counts.items():self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],count)
        self.assertEqual(self.conn.execute('SELECT id FROM question_annotations').fetchone()[0],old['id'])


if __name__=='__main__':unittest.main()
