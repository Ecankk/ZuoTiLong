import json,unittest,tempfile,copy
from pathlib import Path
from app.bank import collection_packs as packs,source_records as records
from app.config import AppConfig
from app.storage.database import Database
import test_source_import as source_tests

class CollectionPackTests(unittest.TestCase):
    def setUp(self):
        self.f=source_tests.SourceImportTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.apply();self.zip=self.f.root/'pack.zip'
        self.target=AppConfig(self.f.root,self.f.root/'target-data',self.f.root/'dist',self.f.root/'target-data'/'learning.db',library=self.f.root/'target-library')

    def test_export_import_empty_library_and_repeat_without_database_change(self):
        exported=packs.export_collection(self.f.config,'zhenti',self.zip)
        self.assertEqual(exported['manifest']['counts']['total'],1)
        self.assertEqual(exported['manifest']['schema'],'mathlens.collection-pack/v2')
        self.assertEqual(exported['manifest']['source_record_count'],1)
        preview=packs.import_collection(self.target,self.zip);self.assertEqual(len(preview['added']),1)
        self.assertFalse(self.target.library_dir.exists());self.assertFalse(self.target.data.exists())
        result=packs.import_collection(self.target,self.zip,preview['plan_sha256']);self.assertTrue(result['applied']);self.assertTrue(Path(result['backup']['path']).is_file())
        again=packs.import_collection(self.target,self.zip);self.assertEqual(len(again['unchanged']),1)
        with packs.connection(self.target) as conn:version=packs._version(conn)
        packs.import_collection(self.target,self.zip,again['plan_sha256'])
        with packs.connection(self.target) as conn:self.assertEqual(packs._version(conn),version)
        self.assertFalse(self.target.data.exists())

    def test_errata_uniqueness_history_markers_and_idempotence(self):
        row=self.f.batch[0]
        entry=dict(match={'source_uid':row['source_uid']},role='analysis',find='1+1',replace='2+0',reason='fixture correction',evidence='independent fixture arithmetic')
        doc=dict(schema='mathlens.bank-errata/v1',source_id='S02',revision=row['revision'],entries=[entry])
        path=self.f.root/'errata.json';path.write_text(json.dumps(doc),encoding='utf8')
        before=copy.deepcopy(row['original']);plan=self.f.run_import(errata=path)
        self.assertEqual(len(plan['errata_applied']),1);self.assertTrue(plan['updated'])
        self.f.run_import(errata=path,confirm=plan['plan_sha256'])
        from app.bank.errata import markers
        with packs.connection(self.f.config) as conn:
            self.assertEqual(markers(conn,records.bank_id(row))[0]['reason'],entry['reason'])
            saved=json.loads(conn.execute('SELECT record_json FROM bank_source_records').fetchone()[0]);self.assertEqual(saved['original'],before)
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_source_versions').fetchone()[0],2)
        self.assertEqual(len(self.f.run_import(errata=path)['unchanged']),1)
        for find in ('missing','1'):
            doc['entries'][0]['find']=find;path.write_text(json.dumps(doc),encoding='utf8')
            with self.assertRaisesRegex(ValueError,'恰好出现一次'):self.f.run_import(errata=path)

    def test_collection_conflict_and_stale_confirmation(self):
        packs.export_collection(self.f.config,'zhenti',self.zip)
        Database(self.target).initialize()
        with Database(self.target).session(write=True,library_write=True) as conn:
            bid=records.bank_id(self.f.batch[0]);conn.execute('INSERT INTO bank_questions(id,source,stem,collection_id,created_at) VALUES(?,?,?,?,?)',(bid,'S02','same id','other','now'))
        plan=packs.import_collection(self.target,self.zip);self.assertEqual(len(plan['collection_conflicts']),1)
        with self.assertRaisesRegex(ValueError,'冲突'):packs.import_collection(self.target,self.zip,plan['plan_sha256'])

    def test_ready_indices_and_catalog_round_trip_and_unchanged_local_annotation(self):
        from test_question_annotations import QuestionPreparationTests
        from app.bank import annotations,annotation_packages
        from app.knowledge import catalog
        source=QuestionPreparationTests();source.setUp();self.addCleanup(source.tearDown)
        ids=source.save_annotation();cfg=source.f.config;zip_path=self.f.root/'ready.zip'
        # Fixture source deliberately uses an identity outside S01, proving that
        # stable existing IDs are retained without inferring source from a title.
        collection=source.conn.execute('SELECT collection_id FROM bank_questions WHERE id=?',(ids[0],)).fetchone()[0]
        exported=packs.export_collection(cfg,collection,zip_path);self.assertEqual(exported['manifest']['counts']['ready'],2)
        original_id=annotations.current(source.conn,source.data,ids[0])['id']
        own=packs.import_collection(cfg,zip_path);self.assertEqual(len(own['unchanged']),2)
        packs.import_collection(cfg,zip_path,own['plan_sha256'])
        self.assertEqual(annotations.current(source.conn,source.data,ids[0])['id'],original_id)
        Database(self.target).initialize()
        with Database(self.target).session(write=True,library_write=True) as conn:
            draft=catalog.create_draft(conn,catalog.base_document(conn),expected_parent=None)
            catalog.publish(conn,draft['id'],expected_parent=None,reviewer='test older directory')
        plan=packs.import_collection(self.target,zip_path);self.assertEqual(plan['catalog']['status'],'upgrade')
        packs.import_collection(self.target,zip_path,plan['plan_sha256'])
        with Database(self.target).session() as conn:
            self.assertEqual({r[0] for r in conn.execute('SELECT id FROM bank_questions')},set(ids))
            self.assertTrue(all(annotations.current(conn,self.target.data,bid)['analysis']['status']=='ready' for bid in ids))
            self.assertEqual(annotation_packages.export_package(conn,self.target.data,collection)['entries'],annotation_packages.export_package(source.conn,source.data,collection)['entries'])

    def test_upload_api_and_errata_markers_on_bank_free_reference_and_agent(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        import uuid
        from app.bank.access import save_preferences
        row=self.f.batch[0];entry=dict(match={'source_uid':row['source_uid']},role='answer',find='A',replace='B',reason='verified print',evidence='fixture')
        path=self.f.root/'errata.json';path.write_text(json.dumps(dict(schema='mathlens.bank-errata/v1',source_id='S02',revision=row['revision'],entries=[entry])),encoding='utf8')
        self.f.apply(errata=path);packs.export_collection(self.f.config,'zhenti',self.zip)
        app=create_app(self.target,agent_factory=None);self.addCleanup(app.state.runtime.close)
        with TestClient(app,base_url='http://127.0.0.1') as http:
            plan=http.post('/api/library/collection-packs/preview',files={'file':('pack.zip',self.zip.read_bytes(),'application/zip')});self.assertEqual(plan.status_code,200,plan.text)
            confirmed=http.post('/api/library/collection-packs/confirm',json={**{k:plan.json()[k] for k in ('package_sha256','plan_sha256')},'confirmed':True});self.assertEqual(confirmed.status_code,200,confirmed.text)
            bid=records.bank_id(row)
            with app.state.runtime.database.session(write=True) as conn:save_preferences(conn,{'mask_same_type':False})
            card=http.get('/api/bank?collection=zhenti&limit=20').json()['items'][0];self.assertEqual(card['errata'][0]['reason'],'verified print')
            http.post(f'/api/bank/{bid}/reveal',json={'role':'analysis','confirmed':True})
            self.assertEqual(http.get(f'/api/bank/{bid}/practice').json()['reference']['errata'][0]['role'],'answer')
            from app.agent import tools
            with __import__('unittest.mock',fromlist=['patch']).patch('app.agent.tools.connection',lambda data:app.state.runtime.database.connect()):
                result=json.loads(tools.execute(self.target.root,self.target.data,'read_bank',{'bank_id':bid,'role':'answer'})[0]['text'])
            self.assertEqual(result['errata'][0]['reason'],'verified print')

    def test_existing_legacy_errata_invalidates_dependent_annotations_and_preserves_id(self):
        from test_question_annotations import QuestionPreparationTests
        from app.bank import annotations
        from app.bank.errata import apply_existing
        source=QuestionPreparationTests();source.setUp();self.addCleanup(source.tearDown)
        ids=source.save_annotation();bid=ids[0]
        collection=source.conn.execute('SELECT collection_id FROM bank_questions WHERE id=?',(bid,)).fetchone()[0]
        doc=dict(schema='mathlens.bank-errata/v1',source_id='S00',revision='legacy-db-export/v1',entries=[dict(match={'source_uid':bid},role='analysis',find='外层sin',replace='外层正弦',reason='text normalization',evidence='same derivative fixture')])
        path=self.f.root/'legacy-errata.json';path.write_text(json.dumps(doc),encoding='utf8')
        plan=apply_existing(source.f.config,path,collection)
        self.assertEqual(set(plan['invalidated_annotations']),set(ids))
        self.assertIsNotNone(annotations.current(source.conn,source.data,bid))
        apply_existing(source.f.config,path,collection,plan['plan_sha256'])
        self.assertIsNone(annotations.current(source.conn,source.data,bid))
        self.assertEqual(source.conn.execute('SELECT count(*) FROM bank_questions WHERE id=?',(bid,)).fetchone()[0],1)
        self.assertTrue(source.conn.execute('SELECT count(*) FROM bank_source_versions WHERE bank_id=?',(bid,)).fetchone()[0]>=2)
        self.assertEqual(len(apply_existing(source.f.config,path,collection)['unchanged']),1)

    def test_confirmation_releases_bridge_lock_while_fencing_other_writes(self):
        import threading
        from unittest.mock import patch
        from fastapi.testclient import TestClient
        from app.main import create_app
        from app.agent.errors import BridgeConflict
        packs.export_collection(self.f.config,'zhenti',self.zip)
        app=create_app(self.target,agent_factory=None);self.addCleanup(app.state.runtime.close)
        class Bridge:
            lock=threading.RLock();preparing=False;workflow_wakeup=threading.Event()
            state={'turns':[],'active_request':None,'status':'idle','external_control':False}
            def assert_user_write_allowed(self):
                if self.preparing:raise BridgeConflict('maintenance busy')
            def availability(self):return dict(status='available',reason=None,message='ready')
            def close(self):pass
        with TestClient(app,base_url='http://127.0.0.1') as http:
            plan=http.post('/api/library/collection-packs/preview',files={'file':('pack.zip',self.zip.read_bytes())}).json()
            bridge=Bridge();app.state.runtime.bridge=bridge;entered=threading.Event();release=threading.Event();responses=[]
            def slow(*args):entered.set();release.wait(5);return {'applied':True}
            with patch('app.api.collection_packs.run',side_effect=slow):
                worker=threading.Thread(target=lambda:responses.append(http.post('/api/library/collection-packs/confirm',json={**{k:plan[k] for k in ('package_sha256','plan_sha256')},'confirmed':True})))
                worker.start()
                try:
                    self.assertTrue(entered.wait(2));self.assertTrue(bridge.preparing)
                    self.assertTrue(bridge.lock.acquire(blocking=False));bridge.lock.release()
                    self.assertEqual(http.get('/api/tasks').status_code,200)
                    self.assertEqual(http.post('/api/preferences',json={'mask_same_type':False}).status_code,409)
                finally:release.set();worker.join(5)
            self.assertEqual(responses[0].status_code,200);self.assertFalse(bridge.preparing)

    def test_invalid_archive_and_pending_status_are_preserved(self):
        import zipfile
        bad=self.f.root/'bad.zip'
        with zipfile.ZipFile(bad,'w') as archive:
            archive.writestr('manifest.json','{}');archive.writestr('../escape','bad')
        with self.assertRaises(ValueError):packs.import_collection(self.target,bad)
        from test_question_annotations import QuestionPreparationTests
        from app.learning.tasks import finish_task
        source=QuestionPreparationTests();source.setUp();self.addCleanup(source.tearDown)
        source.prepare_catalog();ids=source.seed_questions();source.start('annotate_questions',{'bank_ids':ids});source.read_annotation_material()
        source.tool('apply_report',{'result':source.envelope(source.annotation_result(status='needs_review'))});finish_task(source.conn,source.task['id']);source.conn.commit()
        group=source.conn.execute('SELECT collection_id FROM bank_questions WHERE id=?',(ids[0],)).fetchone()[0]
        packs.export_collection(source.f.config,group,self.zip)
        plan=packs.import_collection(self.target,self.zip);self.assertEqual(plan['counts']['needs_review'],1)
        packs.import_collection(self.target,self.zip,plan['plan_sha256'])
        from app.services.knowledge_links import KnowledgeLinksService
        service=KnowledgeLinksService(self.target,Database(self.target))
        # The library import itself does not create a learner DB. Initialize an
        # empty caller workspace only to inspect its normal navigation projection.
        Database(self.target).initialize()
        self.assertEqual(service.topics(ids)['items'][0]['status'],'needs_review')
