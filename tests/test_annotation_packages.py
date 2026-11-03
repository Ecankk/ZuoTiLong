from app.storage.boundaries import library_root
"""Portable ready indices never create a local AI review or learner success."""
import copy
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
import uuid
import threading

from fastapi.testclient import TestClient
from app.bank import annotations, annotation_packages as packages
from app.bank.access import init_access, save_preferences
from app.config import AppConfig
from app.knowledge import catalog, packages as catalog_packages, preparation
from app.main import create_app
from app.storage.database import Database
from app.storage import annotation_cache as store

ROOT = Path(__file__).resolve().parents[1]
TOPIC = 'GS-04-001'


def signed(value):
    value = copy.deepcopy(value)
    for entry in value['entries']:
        entry['sha256'] = packages._sha(entry)
    value['sha256'] = packages._sha(value)
    return value


class AnnotationPackageTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.source = QuestionPreparationTests(); self.source.setUp()
        self.addCleanup(self.source.tearDown)
        self.source.save_annotation()
        self.package = packages.export_package(self.source.conn, self.source.data)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT/'tmp', prefix='index-target-')
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.config = AppConfig(ROOT, self.data, ROOT/'dist', self.data/'mathlens.db')
        self.db = Database(self.config); self.db.initialize(); self.conn = self.db.connect(library_write=True)
        self.addCleanup(self.conn.close)
        directory = catalog_packages.export_package(self.source.conn)
        catalog_packages.import_package(self.conn, directory, trusted_sha256=directory['sha256'], expected_parent=None, confirmed=True)
        self.bid = 'math3-2018-11'
        self.seed(self.bid)

    def seed(self, bid):
        original = self.source.conn.execute('SELECT * FROM bank_questions LIMIT 1').fetchone()
        self.conn.execute('''INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at)
            VALUES(?,?,?,?,?,'now')''', (bid, 'isolated-shared', original['stem'], original['answer'], original['explanation']))
        init_access(self.conn); self.conn.commit()

    def protected(self):
        return {n: self.conn.execute('SELECT count(*) FROM '+n).fetchone()[0]
                for n in ('papers','probe_attempts','learning_events','bank_views','bank_exposures',
                          'learning_tasks','learning_results','task_reads','question_annotations')}

    def accept(self, package=None, **overrides):
        package = package or self.package
        p = packages.preview(self.conn, self.data, package)
        args = {'trusted_sha256': package['sha256'], 'expected_preview_sha256': p['preview_sha256'], 'confirmed': True}
        args.update(overrides)
        result = packages.import_package(self.conn, self.data, package, **args)
        self.conn.commit()
        return result

    def test_fresh_library_reuses_exact_materials_without_fake_tasks_or_attempts(self):
        before = self.protected()
        self.assertEqual(self.accept()['imported'], 1)
        self.assertEqual(before, self.protected())
        value = annotations.current(self.conn, self.data, self.bid)
        self.assertEqual(value['analysis']['status'], 'ready')
        self.assertIn('cache_provenance', value)
        self.assertIsNone(value['analysis']['reference_reasoning'])
        self.assertIsNone(store.record(self.conn, value['id'])['result_id'])
        summary = annotations.prepared_summary(value)
        self.assertNotIn('reference_reasoning', summary)
        self.assertIn('共享', summary['reading'])

    def test_export_whitelist_contains_no_body_ids_paths_or_ai_identity(self):
        text = catalog.encode(self.package)
        for private in ('sin(x', '链式求导', 'same-session', 'reference_reasoning', 'task_id', 'result_id',
                        'bank_id', 'bank-assets', 'source_ref', 'answer_check', 'fingerprint"'):
            self.assertNotIn(private, text)
        self.assertEqual(packages.validate_package(self.package)['entries'], 1)

    def test_import_acceptance_digest_and_preview_are_all_required(self):
        for change in ({'confirmed': False}, {'trusted_sha256': '0'*64}, {'expected_preview_sha256': '0'*64}):
            with self.assertRaises(ValueError): self.accept(**change)
        self.assertEqual(store.listing(self.conn), [])

    def test_repeated_import_is_idempotent_and_new_matching_library_can_be_added(self):
        first = packages.preview(self.conn, self.data, self.package)
        self.accept()
        count = self.conn.execute('SELECT count(*) FROM imported_question_annotations').fetchone()[0]
        again = packages.import_package(self.conn, self.data, self.package, trusted_sha256=self.package['sha256'],
            expected_preview_sha256=first['preview_sha256'], confirmed=True)
        self.assertTrue(again['reused'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM imported_question_annotations').fetchone()[0], count)
        self.seed('math2-2019-11')
        self.assertEqual(self.accept()['imported'], 1)

    def test_same_question_with_different_reference_is_not_imported(self):
        self.conn.execute("UPDATE bank_questions SET explanation='different unreviewed reference' WHERE id=?", (self.bid,)); self.conn.commit()
        self.assertEqual(packages.preview(self.conn, self.data, self.package)['matched_local_records'], 0)
        self.accept()
        self.assertIsNone(annotations.current(self.conn, self.data, self.bid))

    def test_changed_local_material_after_preview_rejects_write(self):
        p = packages.preview(self.conn, self.data, self.package)
        self.conn.execute("UPDATE bank_questions SET answer='different' WHERE id=?", (self.bid,)); self.conn.commit()
        with self.assertRaisesRegex(ValueError, '变化'):
            self.accept(expected_preview_sha256=p['preview_sha256'])
        self.assertEqual(store.listing(self.conn), [])

    def test_changed_definition_invalidates_index_but_alias_changes_do_not(self):
        self.accept()
        def change(field, value):
            document = catalog.base_document(self.conn)
            next(n for n in document['nodes'] if n['id']==TOPIC)[field] = value
            parent=catalog.active_id(self.conn); d=catalog.create_draft(self.conn,document,expected_parent=parent)
            catalog.publish(self.conn,d['id'],expected_parent=parent,reviewer='isolated-change'); self.conn.commit()
        change('aliases', ['same mathematical concept'])
        self.assertIsNotNone(annotations.current(self.conn, self.data, self.bid))
        change('conditions', ['a different mathematical domain'])
        self.assertIsNone(annotations.current(self.conn, self.data, self.bid))
        self.assertEqual(packages.preview(self.conn,self.data,self.package)['omitted']['knowledge_mismatch'], 1)

    def test_raw_or_resigned_unknown_fields_are_never_imported(self):
        value=copy.deepcopy(self.package); value['entries'][0]['dependencies'][TOPIC]='0'*64
        with self.assertRaisesRegex(ValueError,'散列'): packages.validate_package(value)
        for key in ('reference_reasoning','question','student_id','session_id','path'):
            value=copy.deepcopy(self.package); value['entries'][0][key]='secret'
            with self.assertRaisesRegex(ValueError,'夹带'): packages.validate_package(signed(value))
        value=copy.deepcopy(self.package); value['entries'][0]['bindings'][0]['topic_id']=[]
        with self.assertRaises(ValueError): packages.validate_package(signed(value))

    def test_conflicting_indices_for_same_materials_are_not_chosen_by_order(self):
        value=copy.deepcopy(self.package); second=copy.deepcopy(value['entries'][0])
        second['bindings'][0]['stages']=['entry']; value['entries'].append(second); value=signed(value)
        p=packages.preview(self.conn,self.data,value)
        self.assertEqual(p['matched_local_records'],0)
        self.assertEqual(p['omitted']['conflicting_entries'],1)

    def test_import_transaction_rolls_back_partial_rows_and_package_receipt(self):
        self.seed('math2-2019-11')
        self.conn.execute("CREATE TRIGGER library.fail_second_index BEFORE INSERT ON imported_question_annotations WHEN NEW.bank_id=? BEGIN SELECT RAISE(ABORT,'injected import failure'); END".replace('?', "'"+self.bid+"'"))
        self.conn.commit(); before=self.protected()
        with self.assertRaisesRegex(sqlite3.IntegrityError,'injected'):
            self.accept()
        self.assertEqual(store.listing(self.conn),[])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM imported_annotation_topics').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM annotation_cache_imports').fetchone()[0],0)
        self.assertEqual(before,self.protected())

    def test_disable_preserves_history_and_removes_new_recall_then_can_restore(self):
        self.accept(); before=self.protected()
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=[TOPIC])['total'],1)
        with self.assertRaises(ValueError): packages.set_enabled(self.conn,self.package['sha256'],False,confirmed=False)
        packages.set_enabled(self.conn,self.package['sha256'],False,confirmed=True)
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=[TOPIC])['total'],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM imported_question_annotations').fetchone()[0],1)
        packages.set_enabled(self.conn,self.package['sha256'],True,confirmed=True)
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=[TOPIC])['total'],1)
        self.assertEqual(before,self.protected())

    def test_matching_method_hash_and_reservation_protection_keep_existing_semantics(self):
        self.accept()
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=[TOPIC],methods=['链式求导'])['total'],1)
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=[TOPIC],methods=['other'])['total'],0)
        save_preferences(self.conn,{'study_type':3,'mask_same_type':True,'reserved':[{'math_type':3,'year':'2018'}]})
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=[TOPIC])['total'],0)

    def test_original_local_mathematical_review_is_not_overwritten(self):
        before=self.source.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0]
        p=packages.preview(self.source.conn,self.source.data,self.package)
        self.assertEqual(p['matched_local_records'],0)
        self.assertGreater(p['omitted']['already_reviewed_locally'],0)
        self.assertEqual(self.source.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],before)

    def test_preparation_reuses_imported_index_without_an_agent_job(self):
        self.accept(); jobs=self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0]
        run=preparation.start(self.conn,ROOT,self.data,kind='questions',request_id=str(uuid.uuid4()))['runs'][0]
        self.assertEqual(run['status'],'completed'); self.assertEqual(run['counts'],{'completed':1})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM workflow_jobs').fetchone()[0],jobs)

    def test_reexport_preserves_metadata_and_does_not_create_a_local_review(self):
        self.accept(); before=self.protected()
        self.assertEqual(packages.export_package(self.conn,self.data),self.package)
        self.assertEqual(self.protected(),before)

    def test_published_shared_proof_survives_removal_of_private_execution_evidence(self):
        self.source.conn.execute("UPDATE learning_tasks SET status='result_saved' WHERE kind='annotate_questions'")
        self.source.conn.execute("DELETE FROM task_reads WHERE kind='bank_preparation' AND role='analysis'")
        self.assertEqual(packages.export_package(self.source.conn,self.source.data),self.package)
        self.source.conn.execute("UPDATE annotation_provenance SET payload_json=json_set(payload_json,'$.published',0)")
        with self.assertRaisesRegex(ValueError,'没有'): packages.export_package(self.source.conn,self.source.data)

    def test_material_paths_are_local_but_question_and_reference_content_must_match(self):
        from PIL import Image
        from app.learning.tasks import finish_task
        folder=library_root(self.source.data)/'bank-assets';folder.mkdir(exist_ok=True)
        Image.new('RGB',(12,12),'white').save(folder/'original-question.png')
        original=self.source.conn.execute('SELECT id FROM bank_questions ORDER BY id LIMIT 1').fetchone()[0]
        self.source.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',
                                 (original,'{}','bank-assets/original-question.png',None,None));self.source.conn.commit()
        self.source.start('annotate_questions',{'bank_ids':[original]});self.source.read_annotation_material()
        self.source.tool('apply_report',{'result':self.source.envelope(self.source.annotation_result())})
        finish_task(self.source.conn,self.source.task['id']);self.source.conn.commit()
        package=packages.export_package(self.source.conn,self.source.data)
        local=library_root(self.data)/'bank-assets/mirrored';local.mkdir(parents=True)
        (local/'question-local.png').write_bytes((folder/'original-question.png').read_bytes())
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',
                          (self.bid,'{}','bank-assets/mirrored/question-local.png',None,None));self.conn.commit()
        self.assertEqual(self.accept(package)['imported'],1)
        self.assertEqual(annotations.current(self.conn,self.data,self.bid)['analysis']['status'],'ready')
        Image.new('RGB',(12,12),'red').save(local/'question-local.png')
        self.assertIsNone(annotations.current(self.conn,self.data,self.bid))

    def test_busy_agent_blocks_import_through_existing_serial_write_guard(self):
        from app.agent.errors import BridgeConflict
        class Busy:
            lock=threading.RLock()
            def assert_user_write_allowed(self): raise BridgeConflict('等待本轮完成')
        self.conn.commit();p=packages.preview(self.conn,self.data,self.package)
        body={'package':self.package,'trusted_sha256':self.package['sha256'],
              'expected_preview_sha256':p['preview_sha256'],'confirmed':True}
        with TestClient(create_app(self.config,bridge=Busy(),agent_factory=None,manage_agent=False),base_url='http://127.0.0.1') as http:
            self.assertEqual(http.post('/api/knowledge/question-index/import',json=body).status_code,409)
        self.assertEqual(store.listing(self.conn),[])

    def test_http_preview_import_export_and_no_content_search(self):
        self.conn.commit()
        with TestClient(create_app(self.config,agent_factory=None),base_url='http://127.0.0.1') as http:
            p=http.post('/api/knowledge/question-index/preview',json={'package':self.package})
            self.assertEqual(p.status_code,200,p.text)
            body={'package':self.package,'trusted_sha256':self.package['sha256'],
                  'expected_preview_sha256':p.json()['preview_sha256'],'confirmed':True}
            self.assertEqual(http.post('/api/knowledge/question-index/import',json=body).status_code,200)
            listing=http.get('/api/knowledge/question-index').json()
            self.assertEqual(listing['packages'][0]['local_records'],1)
            self.assertEqual(http.get('/api/knowledge/question-index/export').json(),self.package)
            result=http.get('/api/bank/search',params={'topic_id':TOPIC}).json()
            self.assertEqual(result['items'][0]['id'],self.bid)
            self.assertNotIn('reference_reasoning',json.dumps(result))
            self.assertEqual(http.post('/api/knowledge/question-index/import',json=body,headers={'Origin':'http://elsewhere'}).status_code,403)


if __name__=='__main__': unittest.main()
