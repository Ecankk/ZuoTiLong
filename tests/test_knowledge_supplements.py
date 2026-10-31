from app.storage.boundaries import library_root
import copy
import hashlib
import json
from pathlib import Path
import unittest
import uuid
from app.knowledge import candidates,catalog,preparation

ROOT=Path(__file__).resolve().parents[1]


class SupplementSourceTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        self.fixture=KnowledgeCatalogTests();self.fixture.setUp()
        self.conn=self.fixture.conn;self.data=self.fixture.data
        self.folder=self.data/'supplement';self.folder.mkdir()
        raw=b'Isolated mathematical source evidence.'
        (self.folder/'evidence.html').write_bytes(raw)
        self.value={'schema_version':'mathlens.knowledge-source/v1','source':'project-foundations',
            'title':'Isolated source supplement','references':[{'id':'reference-1','title':'Test source',
                'url':'https://example.org/calculus','locator':'section 1','retrieved_at':'2026-10-27',
                'path':'evidence.html','sha256':hashlib.sha256(raw).hexdigest()}],
            'entries':[{'id':'SUP-001','chapter_key':'differentiation','statement':'Composite derivative rule.',
                'conditions':['Inner and outer functions differentiable.'],'boundaries':['Not a statement about continuity only.'],
                'reference_ids':['reference-1'],'source_locator':'section 1, derivative formula'}]}
        self.write()
    def tearDown(self):self.fixture.tearDown()
    def write(self):
        self.value['revision']=catalog.digest({k:v for k,v in self.value.items() if k!='revision'})
        (self.folder/'index.json').write_text(json.dumps(self.value,ensure_ascii=False),encoding='utf-8')
    def import_pack(self):return candidates.import_source(self.conn,self.folder)

    def test_import_is_idempotent_versioned_and_never_publishes_or_writes_student_events(self):
        before={t:self.conn.execute('SELECT count(*) FROM '+t).fetchone()[0] for t in ('knowledge_nodes','learning_events','probe_attempts')}
        first=self.import_pack();self.assertEqual(first['atoms'],1)
        self.assertTrue(self.import_pack()['reused'])
        # Insignificant JSON whitespace is not a new mathematical source.
        (self.folder/'index.json').write_text(json.dumps(self.value,indent=2),encoding='utf-8')
        self.assertTrue(self.import_pack()['reused'])
        rows=candidates.browse(self.conn,source_version_id=first['source_version_id'])
        self.assertEqual(rows['items'][0]['source_import_status'],'source_unreviewed')
        self.assertEqual(rows['items'][0]['catalog_disposition'],'pending')
        self.assertIsNone(catalog.active_id(self.conn))
        for table,count in before.items():self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],count)
        self.value['entries'][0]['conditions'].append('An additional explicit mathematical restriction.')
        self.write();second=self.import_pack()
        self.assertNotEqual(first['source_version_id'],second['source_version_id'])
        self.assertEqual(candidates.browse(self.conn,source_version_id=first['source_version_id'])['total'],1)

    def test_tampered_evidence_or_manifest_revision_never_partially_imports(self):
        before=self.conn.execute('SELECT count(*) FROM knowledge_source_versions').fetchone()[0]
        (self.folder/'evidence.html').write_bytes(b'different bytes')
        with self.assertRaisesRegex(ValueError,'散列'):self.import_pack()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_source_versions').fetchone()[0],before)
        self.value['references'][0]['sha256']=hashlib.sha256(b'different bytes').hexdigest()
        (self.folder/'index.json').write_text(json.dumps(self.value),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'版本'):self.import_pack()

    def test_references_must_exist_within_the_pack_and_without_credentials(self):
        self.value['references'][0]['path']='../candidate/chapter.json';self.write()
        with self.assertRaisesRegex(ValueError,'路径'):self.import_pack()
        self.value['references'][0]['path']='evidence.html'
        self.value['references'][0]['url']='https://user:password@example.org/math';self.write()
        with self.assertRaisesRegex(ValueError,'URL'):self.import_pack()

    def test_duplicate_or_unknown_references_and_personal_fields_are_rejected(self):
        original=copy.deepcopy(self.value)
        self.value['entries'][0]['reference_ids']=['missing'];self.write()
        with self.assertRaisesRegex(ValueError,'依据'):self.import_pack()
        self.value=copy.deepcopy(original);self.value['entries'].append(copy.deepcopy(self.value['entries'][0]));self.write()
        with self.assertRaisesRegex(ValueError,'重复'):self.import_pack()
        self.value=copy.deepcopy(original);self.value['entries'][0]['mastery']='mastered';self.write()
        with self.assertRaisesRegex(ValueError,'个人状态'):self.import_pack()

    def test_catalogue_batches_use_declared_chapters_not_id_spelling(self):
        second=copy.deepcopy(self.value['entries'][0]);second['id']='UNRELATED-777'
        third=copy.deepcopy(self.value['entries'][0]);third.update(id='SUP-002',chapter_key='other-chapter')
        self.value['entries']+=[third,second];self.write()
        source=self.import_pack()
        run=preparation.start(self.conn,ROOT,self.data,kind='catalog',request_id=str(uuid.uuid4()),
                              source_version_id=source['source_version_id'],batch_size=10)
        job=self.conn.execute('SELECT scope_json FROM workflow_jobs WHERE workflow_id=?',(run['runs'][0]['id'],)).fetchone()
        self.assertEqual(set(json.loads(job[0])['source_ids']),{'SUP-001','UNRELATED-777'})

    def test_existing_http_import_and_task_tools_accept_the_new_candidate_format(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        from test_question_annotations import QuestionPreparationTests
        self.conn.commit()
        with TestClient(create_app(self.fixture.config,agent_factory=None),base_url='http://127.0.0.1') as http:
            response=http.post('/api/knowledge/preparation/import',json={'directory':str(self.folder)})
            self.assertEqual(response.status_code,200,response.text)
            source=response.json()['source_version_id']
        # Read actual source via the same scoped tool path, then publish a
        # synthetic canonical node. No learner paper/session is fabricated.
        f=QuestionPreparationTests()
        f.f=self.fixture;f.conn=self.conn;f.data=self.data;f.root=ROOT;f.task=None;f.lease=None
        f.start('maintain_catalog',{'source_version_id':source,'source_ids':['SUP-001']})
        read=f.tool('task_context',{'source_ids':['SUP-001']})['source_entries'][0]
        self.assertEqual(read['content']['record']['references'][0]['sha256'],self.value['references'][0]['sha256'])
        result=f.maintenance_result();node=result['node_changes'][0]
        node['source_refs']=[{'source_version_id':source,'source_id':'SUP-001'}]
        result['source_resolutions'][0]['source_id']='SUP-001'
        saved=f.tool('apply_report',{'result':f.envelope(result)})
        from app.learning.tasks import receipt
        self.assertEqual(receipt(self.conn,f.task['id'])['result_id'],saved['result_id'])
        self.assertIsNotNone(catalog.active_id(self.conn))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM papers').fetchone()[0],0)

    def service(self):
        from app.services.knowledge_catalog import KnowledgeCatalogService
        from app.storage.database import Database
        self.conn.commit()
        return KnowledgeCatalogService(self.fixture.config,Database(self.fixture.config))

    def test_import_preserves_evidence_and_can_reuse_it_after_original_is_removed(self):
        service=self.service();saved=service.import_candidates(self.folder)
        archive=library_root(self.data)/saved['evidence_root']
        self.assertEqual(candidates.read_supplement(archive),candidates.read_supplement(self.folder))
        (self.folder/'index.json').unlink();(self.folder/'evidence.html').unlink();self.folder.rmdir()
        reused=service.import_candidates(archive)
        self.assertTrue(reused['reused'])
        self.assertEqual(reused['evidence_root'],saved['evidence_root'])
        metadata=json.loads(self.conn.execute('SELECT metadata_json FROM knowledge_source_versions WHERE id=?',
                                             (saved['source_version_id'],)).fetchone()[0])
        self.assertEqual(metadata['evidence_root'],saved['evidence_root'])

    def test_existing_archive_tamper_is_rejected_without_silently_repairing_it(self):
        service=self.service();saved=service.import_candidates(self.folder)
        archive=library_root(self.data)/saved['evidence_root'];(archive/'evidence.html').write_bytes(b'tampered')
        before=self.conn.execute('SELECT * FROM knowledge_source_versions').fetchall()
        with self.assertRaisesRegex(ValueError,'散列'):service.import_candidates(self.folder)
        self.assertEqual((archive/'evidence.html').read_bytes(),b'tampered')
        self.assertEqual(self.conn.execute('SELECT * FROM knowledge_source_versions').fetchall(),before)

    def test_evidence_storage_failure_rolls_back_new_candidate_rows(self):
        from unittest.mock import patch
        service=self.service()
        before={table:self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0]
                for table in ('knowledge_source_versions','knowledge_source_entries')}
        with patch('app.storage.knowledge_sources.preserve_supplement',side_effect=OSError('disk failure')):
            with self.assertRaisesRegex(OSError,'disk failure'):service.import_candidates(self.folder)
        for table,count in before.items():
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],count)

    def test_backup_and_restore_keep_original_source_bytes_without_import_folder(self):
        from app.storage.maintenance import backup,restore
        service=self.service();saved=service.import_candidates(self.folder)
        expected=candidates.read_supplement(library_root(self.data)/saved['evidence_root'])
        (self.folder/'index.json').unlink();(self.folder/'evidence.html').unlink();self.folder.rmdir()
        result=backup(self.data,ROOT)
        destination=self.data/'restored';restore(Path(result['path']),destination)
        self.assertEqual(candidates.read_supplement(library_root(destination)/saved['evidence_root']),expected)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],0)


if __name__=='__main__':unittest.main()
