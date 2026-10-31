from app.storage.boundaries import library_root
"""Read-only navigation must agree in both directions without learner writes."""
import copy
import json
import unittest
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.knowledge_links import KnowledgeLinksService,public_topics
from app.storage.database import Database
from app.bank import annotations
from app.bank.access import init_access, save_preferences
from app.knowledge import catalog
from app.learning.tasks import finish_task

TOPIC='GS-04-001'
PARENT='math1.calculus.differentiation'


class KnowledgeLinksTests(unittest.TestCase):
    def setUp(self):
        from test_question_annotations import QuestionPreparationTests
        self.f=QuestionPreparationTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.ids=self.f.save_annotation();self.conn=self.f.conn
        self.config=self.f.f.config;self.db=Database(self.config)
        self.service=KnowledgeLinksService(self.config,self.db)

    def tables(self):
        return {r[0]:[tuple(v) for v in self.conn.execute('SELECT * FROM '+r[0]+' ORDER BY rowid')]
                for r in self.conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}

    def test_forward_reverse_summary_and_subtree_agree_without_any_writes(self):
        before=self.tables()
        page=self.service.links(topic_id=TOPIC)
        self.assertEqual(page['total'],1);self.assertEqual(page['source_records'],2)
        self.assertEqual({s['bank_id'] for s in page['items'][0]['sources']},set(self.ids))
        for item in self.service.topics(self.ids)['items']:
            self.assertEqual(item['topics'][0]['topic_id'],TOPIC)
            self.assertEqual(item['topics'][0]['role'],'primary')
        self.assertEqual(self.service.links(topic_id=PARENT)['total'],1)
        self.assertEqual(self.service.links(topic_id=PARENT,scope='self')['total'],0)
        summary=self.service.summary()
        self.assertEqual(summary['nodes'][TOPIC],{'bank':1,'ready':1,'completed':0,'source_records':2})
        self.assertEqual(summary['nodes'][PARENT],summary['nodes'][TOPIC])
        self.assertEqual(summary['default_view'],'bank')
        self.assertEqual(summary['navigation_revision'],page['navigation_revision'])
        self.assertEqual(self.tables(),before)

    def test_browsing_keeps_reserved_exposed_and_attempted_candidates(self):
        save_preferences(self.conn,{'study_type':1,'reserved':[{'math_type':1,'year':'2020'}]})
        self.conn.execute("INSERT INTO bank_views VALUES(?,'analysis','now')",(self.ids[0],))
        self.conn.execute("INSERT INTO bank_exposures VALUES(?,'now')",(self.ids[0],));self.conn.commit()
        self.assertEqual(annotations.matching(self.conn,self.f.data,topic_ids=[TOPIC])[1],[])
        page=self.service.links(topic_id=TOPIC)
        self.assertEqual(page['total'],1)
        self.assertTrue(next(s for s in page['items'][0]['sources'] if s['bank_id']==self.ids[0])['reserved'])
        self.assertTrue(all(s['reserved'] for s in page['items'][0]['sources']))

    def test_no_reasoning_answers_paths_or_fingerprints_in_navigation(self):
        combined=json.dumps([self.service.links(topic_id=TOPIC),self.service.topics(self.ids),self.service.summary()])
        for forbidden in ('reference_reasoning','answer_check','fingerprint','checkpoints','student_work','image_sha256','path','独立推导'):
            self.assertNotIn(forbidden,combined)
        self.assertIn('primary',combined)

    def test_material_change_invalidates_cached_links_without_manual_refresh(self):
        self.assertEqual(self.service.links(topic_id=TOPIC)['total'],1)
        self.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('a changed reference',self.ids[0]));self.conn.commit()
        item=self.service.topics([self.ids[0]])['items'][0]
        self.assertEqual(item['status'],'outdated');self.assertEqual(item['topics'],[])
        # This shared annotation was reviewed against the original canonical
        # reference. Changing that reference invalidates its aliases as well.
        self.assertEqual(self.service.links(topic_id=TOPIC)['source_records'],0)

    def test_definition_change_invalidates_both_directions(self):
        self.service.summary()
        value=copy.deepcopy(catalog.document(self.conn)['document'])
        next(n for n in value['nodes'] if n['id']==TOPIC)['conditions'].append('Additional reviewed condition.')
        parent=catalog.active_id(self.conn);draft=catalog.create_draft(self.conn,value,expected_parent=parent)
        catalog.publish(self.conn,draft['id'],expected_parent=parent,reviewer='isolated-content-review');self.conn.commit()
        self.assertEqual(self.service.links(topic_id=TOPIC)['total'],0)

        self.assertTrue(all(not i['topics'] for i in self.service.topics(self.ids)['items']))

    def test_merged_old_ids_display_once_without_retagging_saved_analysis(self):
        bindings=[{'topic_id':'old','role':'prerequisite','stages':['entry']},
                  {'topic_id':TOPIC,'role':'primary','stages':['formula']}]
        before=copy.deepcopy(bindings)
        value=public_topics(bindings,{TOPIC:'Chain rule'},lambda tid:TOPIC)
        self.assertEqual(value,[{'topic_id':TOPIC,'name':'Chain rule','role':'primary','stages':['entry','formula']}])
        self.assertEqual(bindings,before)

    def test_another_readers_cache_key_cannot_change_this_snapshot_revision(self):
        from unittest.mock import patch
        first=self.service.summary();original=self.service._completed
        def competing_reader(*args):
            result=original(*args);self.service._bank_key='a-newer-reader-snapshot';return result
        with patch.object(self.service,'_completed',side_effect=competing_reader):
            self.assertEqual(self.service.summary(),first)

    def test_slow_material_validation_does_not_hold_a_lock_on_learning_writes(self):
        from unittest.mock import patch
        import threading,time
        entered=threading.Event();release=threading.Event();errors=[]
        original=annotations.current
        def slow(*args,**kwargs):
            entered.set()
            if not release.wait(5):raise TimeoutError('test barrier')
            return original(*args,**kwargs)
        def read():
            try:self.service.summary()
            except BaseException as error:errors.append(error)
        with patch.object(annotations,'current',side_effect=slow):
            reader=threading.Thread(target=read);reader.start()
            try:
                self.assertTrue(entered.wait(5))
                writer=self.db.connect();writer.execute('PRAGMA busy_timeout=200')
                try:
                    writer.execute('UPDATE preferences SET payload=payload WHERE id=1');writer.commit()
                finally:writer.close()
            finally:release.set();reader.join(10)
        self.assertFalse(reader.is_alive());self.assertEqual(errors,[])

    def test_current_needs_review_not_replaced_by_old_ready(self):
        self.f.start('annotate_questions',{'bank_ids':self.ids})
        self.f.read_annotation_material();value=self.f.annotation_result('needs_review')
        value['questions'][0]['bindings']=[{'topic_id':TOPIC,'role':'primary','evidence':'The known chain-rule part remains valid.','stages':['formula']}]
        self.f.tool('apply_report',{'result':self.f.envelope(value)})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        summary=self.service.summary()['nodes'][TOPIC]
        self.assertEqual(summary['bank'],1);self.assertEqual(summary['ready'],0)
        self.assertTrue(all(i['status']=='needs_review' for i in self.service.topics(self.ids)['items']))

    def test_unannotated_kept_in_full_bank_but_not_falsely_linked(self):
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('math3-2025-01','isolated','new question','now')")
        init_access(self.conn);self.conn.commit()
        self.assertEqual(self.service.links()['total'],2)
        item=self.service.topics(['math3-2025-01'])['items'][0]
        self.assertEqual(item['status'],'unannotated');self.assertEqual(item['topics'],[])
        self.assertEqual(self.service.links(topic_id=TOPIC)['total'],1)

    def test_pagination_roles_categories_and_empty_personal_history(self):
        self.assertEqual(self.service.links(view='completed',topic_id=TOPIC)['total'],0)
        self.assertEqual(self.service.links(topic_id=TOPIC,role='prerequisite')['total'],0)
        page=self.service.links(math_type=2,limit=1)
        self.assertEqual(page['source_records'],1)
        self.assertEqual(page['items'][0]['sources'][0]['math_type'],2)
        self.assertIsNone(page['next_offset'])
        self.assertEqual(self.service.links(offset=1000)['items'],[])
        for kwargs in ({'view':'pending'},{'scope':'unsafe'},{'limit':0},{'offset':-1},{'role':'solution'},{'math_type':True}):
            with self.assertRaises(ValueError):self.service.links(**kwargs)

    def test_old_id_redirect_has_same_topic_set(self):
        value=copy.deepcopy(catalog.document(self.conn)['document']);target='canonical.chain'
        next(n for n in value['nodes'] if n['id']==TOPIC)['id']=target
        value['redirects'].append({'old_id':TOPIC,'target_id':target,'reason':'Same concept identity.'})
        for resolution in value['source_resolutions']:
            resolution['node_ids']=[target if t==TOPIC else t for t in resolution['node_ids']]
        parent=catalog.active_id(self.conn);draft=catalog.create_draft(self.conn,value,expected_parent=parent)
        catalog.publish(self.conn,draft['id'],expected_parent=parent,reviewer='isolated-review');self.conn.commit()
        page=self.service.links(topic_id=TOPIC)
        self.assertEqual(page['topic_id'],target)
        self.assertEqual(page['total'],1)
        self.assertEqual(self.service.topics(self.ids)['items'][0]['topics'][0]['topic_id'],target)

    def test_actual_http_paths_are_read_only_and_do_not_hit_resource_wildcard(self):
        before=self.tables()
        with TestClient(create_app(self.config,agent_factory=None),base_url='http://127.0.0.1') as client:
            for path in ('/api/knowledge/links/summary','/api/knowledge/links?topic_id='+TOPIC,
                         '/api/bank/'+self.ids[0]+'/topics','/api/bank/topics?bank_id='+self.ids[0]):
                response=client.get(path);self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(client.get('/api/knowledge/links?limit=0').status_code,400)
            self.assertEqual(client.get('/api/knowledge/links?catalog_revision=outdated').status_code,400)
            self.assertEqual(client.get('/api/bank/missing/topics').status_code,400)
        self.assertEqual(before,self.tables())

    def test_read_view_cannot_be_reused_after_a_write_or_outside_transaction(self):
        from app.bank.annotation_view import AnnotationReadView
        with self.assertRaisesRegex(ValueError,'快照'):AnnotationReadView(self.conn,self.f.data)
        with catalog.atomic(self.conn):
            view=AnnotationReadView(self.conn,self.f.data)
            self.assertEqual(annotations.current(self.conn,self.f.data,self.ids[0],read_view=view),
                             annotations.current(self.conn,self.f.data,self.ids[0]))
            self.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('new answer',self.ids[0]))
            with self.assertRaisesRegex(ValueError,'写入'):
                annotations.current(self.conn,self.f.data,self.ids[0],read_view=view)
        with self.assertRaisesRegex(ValueError,'结束'):
            annotations.current(self.conn,self.f.data,self.ids[0],read_view=view)

    def test_file_bytes_change_with_restored_mtime_does_not_leave_cached_ready(self):
        from PIL import Image
        import os
        directory=library_root(self.f.data)/'bank-assets'/'fixture';directory.mkdir(parents=True)
        path=directory/'question.png';Image.new('RGB',(20,20),'blue').save(path)
        relative=path.relative_to(self.f.data).as_posix()
        for bid in self.ids:self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,NULL,NULL)',(bid,'{}',relative))
        self.conn.commit();self.f.start('annotate_questions',{'bank_ids':self.ids});self.f.read_annotation_material()
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.assertEqual(self.service.links(topic_id=TOPIC)['total'],1)
        stat=path.stat();content=bytearray(path.read_bytes());content[-1]^=1;path.write_bytes(content)
        os.utime(path,ns=(stat.st_atime_ns,stat.st_mtime_ns))
        self.assertEqual(self.service.links(topic_id=TOPIC)['total'],0)


class CompletedKnowledgeLinksTests(unittest.TestCase):
    def setUp(self):
        from test_mapping_versions import MappingVersionsTests
        self.f=MappingVersionsTests();self.f.setUp();self.addCleanup(self.f.tearDown)
        self.conn=self.f.conn
        self.config=__import__('app.config',fromlist=['AppConfig']).AppConfig(self.f.f.root,self.f.f.data,self.f.f.root/'dist',__import__('database_fixture').DB_PATH)
        self.service=KnowledgeLinksService(self.config,Database(self.config))

    def prepare_work(self,first='visible',second='not_attempted'):
        report=copy.deepcopy(self.f.f.fixture.report)
        for q,state in zip(report['questions'],(first,second)):
            q['answer_evidence']={'student_state':state,'student_work':'an actual calculation' if state=='visible' else '',
                                  'marking':'none','marking_note':''}
        from app.learning.loop import apply_report
        apply_report(self.conn,'paper-test',report,self.f.f.root);self.conn.commit();self.f.save()

    def test_completed_requires_actual_original_work_and_current_mapping(self):
        self.prepare_work()
        page=self.service.links(view='completed',topic_id=TOPIC)
        self.assertEqual(page['total'],1)
        self.assertEqual(page['items'][0]['sources'][0]['source_kind'],'paper')
        self.assertEqual(page['items'][0]['sources'][0]['state'],'wrong')
        self.assertEqual(self.service.summary()['nodes'][TOPIC]['completed'],1)
        self.assertEqual(self.service.summary()['default_view'],'completed')

    def test_unreadable_or_blank_work_is_not_completed(self):
        self.prepare_work('unreadable','not_attempted')
        self.assertEqual(self.service.links(view='completed')['total'],0)

    def test_partial_work_counts_without_claiming_correct(self):
        self.prepare_work()
        row=self.conn.execute('SELECT * FROM question_diagnoses ORDER BY question_id LIMIT 1').fetchone()
        value=json.loads(row['diagnosis_json']);value['correctness']='partial'
        self.conn.execute('UPDATE question_diagnoses SET diagnosis_json=? WHERE question_id=?',(json.dumps(value),row['question_id']));self.conn.commit()
        page=self.service.links(view='completed')
        self.assertEqual(page['items'][0]['sources'][0]['state'],'partial')

    def test_no_attempt_or_null_assessment_not_completed(self):
        self.prepare_work('not_attempted','not_attempted')
        from app.learning.loop import submit_probe
        probe=self.conn.execute('SELECT id FROM diagnostic_probes LIMIT 1').fetchone()[0]
        attempt=submit_probe(self.conn,probe,{'response':'my work'})['attempt_id']
        self.conn.commit();self.assertEqual(self.service.links(view='completed')['total'],0)
        self.conn.execute('UPDATE probe_attempts SET assessment_json=? WHERE id=?',(json.dumps({'correct':None}),attempt));self.conn.commit()
        self.assertEqual(self.service.links(view='completed')['total'],0)
        self.conn.execute('UPDATE probe_attempts SET assessment_json=? WHERE id=?',(json.dumps({'correct':False}),attempt));self.conn.commit()
        page=self.service.links(view='completed')
        self.assertEqual(page['total'],1)
        self.assertEqual(page['items'][0]['sources'][0]['attempt_id'],attempt)

    def test_archiving_removes_current_completed_records_without_deleting_history(self):
        self.prepare_work();self.assertEqual(self.service.links(view='completed')['total'],1)
        self.conn.execute("UPDATE papers SET archived_at='now' WHERE id='paper-test'");self.conn.commit()
        self.assertEqual(self.service.links(view='completed')['total'],0)
        self.assertGreater(self.conn.execute('SELECT count(*) FROM question_diagnoses').fetchone()[0],0)


class SharedKnowledgeLinksTests(unittest.TestCase):
    def setUp(self):
        from test_annotation_packages import AnnotationPackageTests
        self.f=AnnotationPackageTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.accept();self.service=KnowledgeLinksService(self.f.config,self.f.db)

    def test_explicitly_accepted_shared_index_has_symmetric_tags_without_fake_local_receipt(self):
        before=self.f.protected()
        forward=self.service.topics([self.f.bid])['items'][0]
        reverse=self.service.links(topic_id=TOPIC)
        self.assertEqual(forward['annotation_origin'],'shared')
        self.assertEqual(forward['topics'][0]['topic_id'],TOPIC)
        self.assertEqual(reverse['total'],1)
        self.assertEqual(reverse['items'][0]['sources'][0]['annotation_id'],forward['annotation_id'])
        self.assertEqual(self.f.protected(),before)

    def test_disabling_shared_package_invalidates_cached_counts_and_tags(self):
        self.assertEqual(self.service.summary()['nodes'][TOPIC]['ready'],1)
        from app.bank.annotation_packages import set_enabled
        set_enabled(self.f.conn,self.f.package['sha256'],False,confirmed=True);self.f.conn.commit()
        self.assertEqual(self.service.links(topic_id=TOPIC)['total'],0)
        self.assertEqual(self.service.topics([self.f.bid])['items'][0]['topics'],[])
