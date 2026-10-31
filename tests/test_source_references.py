from app.storage.boundaries import library_root
import copy
import hashlib
import json
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch

import pymupdf
from app.agent.tools import execute
from app.knowledge import catalog, preparation, references
from app.knowledge.maintenance import normalize_scope
from app.learning.tasks import receipt, retry_task, task_package
from app.services.knowledge_catalog import KnowledgeCatalogService
from app.storage.database import Database


class SourceReferenceTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp()
        self.addCleanup(self.f.tearDown)
        self.conn,self.data,self.root=self.f.conn,self.f.data,self.f.root
        self.folder=self.data/'new-source';self.folder.mkdir()
        with pymupdf.open() as document:
            for text in ('Original chain rule and conditions.', 'An independently readable second page.'):
                document.new_page().insert_text((40,50),text)
            document.save(self.folder/'original.pdf')
        raw=(self.folder/'original.pdf').read_bytes()
        self.pack={'schema_version':'mathlens.knowledge-source/v1','source':'reference-reader-fixture',
            'title':'Isolated mathematical source',
            'references':[{'id':'ref-1','title':'Original source','url':'https://example.org/original.pdf',
                'locator':'pages 1 and 2','retrieved_at':'2026-10-27','path':'original.pdf','sha256':hashlib.sha256(raw).hexdigest()}],
            'entries':[{'id':'SUP-SRC-001','chapter_key':'chain-rule','statement':'A composite derivative has two factors.',
                'conditions':['Both relevant functions are differentiable.'],'boundaries':['Not continuity alone.'],
                'reference_ids':['ref-1'],'source_locator':'page 1'}]}
        self.pack['revision']=catalog.digest(self.pack)
        (self.folder/'index.json').write_text(json.dumps(self.pack),encoding='utf-8')
        self.conn.commit()
        service=KnowledgeCatalogService(self.f.f.config,Database(self.f.f.config))
        self.source=service.import_candidates(str(self.folder));self.sid=self.source['source_version_id']
        self.scope={'source_version_id':self.sid,'source_ids':['SUP-SRC-001'],'reference_ids':['ref-1']}
        self.evidence=library_root(self.data)/'knowledge-sources'/self.sid/'original.pdf'

    def start(self,scope=None):
        self.f.start('maintain_catalog',scope or self.scope)
        self.inputs=json.loads(self.f.task['input_json'])
        self.f.tool('task_context',{'source_ids':['SUP-SRC-001']})
    def value(self):
        node=copy.deepcopy(self.f.f.value()['nodes'][-1])
        node.update(id='SUP-SRC-001',source_refs=[{'source_version_id':self.sid,'source_id':'SUP-SRC-001'}])
        return self.f.envelope({'summary':'Source verified in isolation.','node_changes':[node],'redirects':[],
            'source_resolutions':[{'source_id':'SUP-SRC-001','disposition':'mapped','node_ids':['SUP-SRC-001'],'reason':'The actual original matches.'}],
            'limitations':[]})

    def test_pdf_pages_return_pixels_and_text_and_gate_the_transaction(self):
        self.start();before=self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'knowledge_reference'):
            self.f.tool('apply_report',{'result':self.value()})
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        result=execute(self.root,self.data,'task_context',{'reference_id':'ref-1','pages':[2,1]},lease=self.f.lease)
        metadata=json.loads(result[0]['text'])
        self.assertEqual([p['number'] for p in metadata['pages']],[2,1])
        self.assertEqual(metadata['sha256'],self.pack['references'][0]['sha256'])
        self.assertIn('Original chain rule',metadata['pages'][1]['text'])
        self.assertEqual([x['type'] for x in result],['text','image','image'])
        self.f.tool('apply_report',{'result':self.value()})
        self.assertIsNotNone(receipt(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],before)

    def test_unknown_or_invalid_pages_record_no_successful_read(self):
        self.start()
        for pages in ([],[0],[3],[True],[1,1],[1,'2'],None,[1,2,1,2]):
            with self.subTest(pages=pages),self.assertRaises(ValueError):
                self.f.tool('task_context',{'reference_id':'ref-1','pages':pages})
        with self.assertRaisesRegex(ValueError,'捕获范围'):
            self.f.tool('task_context',{'reference_id':'other','pages':[1]})
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_reads WHERE kind='knowledge_reference'").fetchone()[0],0)

    def test_tamper_between_read_and_delivery_is_rejected_with_no_receipt(self):
        self.start();self.f.tool('task_context',{'reference_id':'ref-1','pages':[1]})
        self.evidence.write_bytes(b'%PDF changed after read')
        with self.assertRaisesRegex(ValueError,'散列'):
            self.f.tool('apply_report',{'result':self.value()})
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertIsNone(catalog.active_id(self.conn))

    def test_source_read_does_not_follow_mutated_original_download(self):
        self.start();(self.folder/'original.pdf').write_bytes(b'modified external download')
        value=self.f.tool('task_context',{'reference_id':'ref-1','pages':[1]})
        self.assertIn('Original chain rule',value['pages'][0]['text'])

    def test_paths_cannot_escape_the_archived_source_directory(self):
        self.start()
        for path in ('../outside.pdf',str((self.data/'outside.pdf').resolve())):
            inputs=copy.deepcopy(self.inputs)
            inputs['source_entries'][0]['content']['record']['references'][0]['path']=path
            with self.subTest(path=path),self.assertRaisesRegex(ValueError,'路径'):
                references.material(self.data,inputs,'ref-1')

    def test_required_reference_scope_is_validated_at_capture(self):
        for ids in ([],['ref-1','ref-1'],[False],['missing']):
            with self.subTest(ids=ids),self.assertRaises(ValueError):
                self.f.start('maintain_catalog',{**self.scope,'reference_ids':ids})

    def test_reading_candidates_does_not_count_as_reading_references(self):
        self.start()
        package=task_package(self.conn,self.f.task['id'])
        self.assertEqual(package['input']['task_scope']['reference_ids'],['ref-1'])
        self.assertEqual(self.conn.execute("SELECT count(*) FROM task_reads WHERE kind='knowledge_reference'").fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'knowledge_reference'):
            self.f.tool('apply_report',{'result':self.value()})

    def test_legacy_captured_scope_keeps_original_delivery_and_retry_semantics(self):
        legacy={k:v for k,v in self.scope.items() if k!='reference_ids'}
        self.start(legacy)
        original=self.f.task['input_revision']
        task=retry_task(self.conn,self.root,self.data,self.f.task['id'])
        self.assertEqual(task['input_revision'],original)
        self.conn.commit()
        from app.learning.tasks import bind_turn
        bind_turn(self.conn,task['id'],'same-session',task['run_token'],'retry-turn');self.conn.commit()
        self.f.task=task;self.f.lease.update(run_token=task['run_token'],turn_id='retry-turn')
        self.f.tool('apply_report',{'result':self.value()})
        self.assertIsNotNone(receipt(self.conn,task['id']))

    def test_new_preparation_batch_requires_declared_immutable_evidence(self):
        result=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),
                                 source_version_id=self.sid,batch_size=2)
        rid=result['runs'][0]['id']
        scope=json.loads(self.conn.execute('SELECT scope_json FROM workflow_jobs WHERE workflow_id=?',(rid,)).fetchone()[0])
        self.assertEqual(scope['reference_ids'],['ref-1'])

    def test_bad_reference_is_isolated_instead_of_dispatching_a_false_readable_batch(self):
        self.evidence.write_bytes(b'damaged source')
        result=preparation.start(self.conn,self.root,self.data,kind='catalog',request_id=str(uuid.uuid4()),source_version_id=self.sid)
        self.assertEqual(result['runs'][0]['status'],'needs_review')
        self.assertEqual(result['runs'][0]['counts'],{'needs_review':1})

    def test_html_is_bounded_raw_source_with_external_resource_limit(self):
        self.start();inputs=copy.deepcopy(self.inputs)
        ref=inputs['source_entries'][0]['content']['record']['references'][0]
        ref['path']='original.html';raw=('<html><img src="external-equation.png">'+'x'*30000+'</html>').encode()
        ref['sha256']=hashlib.sha256(raw).hexdigest();self.evidence.with_suffix('.html').write_bytes(raw)
        first,images=references.read(self.data,inputs,{'reference_id':'ref-1'})
        self.assertEqual(first['next_offset'],24000);self.assertEqual(images,[])
        self.assertIn('外部公式',first['reading'])
        last,_=references.read(self.data,inputs,{'reference_id':'ref-1','offset':first['next_offset']})
        self.assertIsNone(last['next_offset'])

    def test_annotation_task_cannot_read_catalogue_source_files(self):
        self.f.prepare_catalog();self.f.seed_questions()
        self.f.start('annotate_questions',{'bank_ids':['math1-2020-01']})
        with self.assertRaisesRegex(ValueError,'只有目录维护'):
            self.f.tool('task_context',{'reference_id':'ref-1','pages':[1]})

    def test_windows_transient_rename_denial_retries_the_same_atomic_publish(self):
        from app.storage.knowledge_sources import publish_evidence
        source=self.data/'publish-staging';source.mkdir();(source/'evidence').write_text('complete')
        target=self.data/'published-evidence';original=Path.replace;calls=[]
        def replace(path,destination):
            calls.append((path,destination))
            if len(calls)==1:
                error=PermissionError('temporary scanner hold');error.winerror=32;raise error
            return original(path,destination)
        with patch.object(Path,'replace',replace),patch('app.storage.knowledge_sources.time.sleep') as sleep:
            publish_evidence(source,target)
        self.assertEqual(len(calls),2);sleep.assert_called_once_with(.05)
        self.assertEqual((target/'evidence').read_text(),'complete');self.assertFalse(source.exists())

    def test_permanent_rename_denial_is_not_reported_as_success(self):
        from app.storage.knowledge_sources import publish_evidence
        source=self.data/'never-published';source.mkdir();target=self.data/'must-not-exist'
        error=PermissionError('held');error.winerror=5
        with patch.object(Path,'replace',side_effect=error) as rename,patch('app.storage.knowledge_sources.time.sleep') as sleep:
            with self.assertRaises(PermissionError):publish_evidence(source,target)
        self.assertEqual(rename.call_count,5);self.assertEqual(sleep.call_count,4)
        self.assertTrue(source.is_dir());self.assertFalse(target.exists())

    def test_non_windows_permission_failure_does_not_retry(self):
        from app.storage.knowledge_sources import publish_evidence
        with patch.object(Path,'replace',side_effect=PermissionError('denied')) as rename,patch('app.storage.knowledge_sources.time.sleep') as sleep:
            with self.assertRaises(PermissionError):publish_evidence(Path('unused'),Path('unused-target'))
        self.assertEqual(rename.call_count,1);sleep.assert_not_called()


if __name__=='__main__':unittest.main()
