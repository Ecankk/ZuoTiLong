import json,threading,unittest,uuid
from unittest.mock import patch

class SelectionConcurrencyTests(unittest.TestCase):
    def setUp(self):
        from test_execution_v2 import ExecutionTests
        self.f=ExecutionTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def writer_can_reserve(self):
        from app.storage.database import Database
        conn=Database(__import__('database_fixture').config()).connect()
        try:conn.execute('PRAGMA busy_timeout=0');conn.execute('BEGIN IMMEDIATE');conn.rollback()
        finally:conn.close()

    def test_capture_and_normalize_run_without_write_reservation_and_template_is_complete(self):
        from app.learning import tasks,selection
        original=selection.capture
        def checked(*args):self.writer_can_reserve();return original(*args)
        with patch.object(selection,'capture',side_effect=checked):packet,scope=self.f.selection()
        template=json.loads(packet[0]['text'])['result_template']['result']['limitations']
        self.assertEqual(set(template),{t['goal']['id'] for t in scope['targets']})
        original_normalize=selection.normalize
        def normalized(*args):self.writer_can_reserve();return original_normalize(*args)
        # Only the preparatory normalization is expected; the write phase uses it.
        with patch.object(selection,'normalize',side_effect=normalized) as normalize:
            tasks.deliver(self.f.conn,self.f.root,self.f.data,self.f.selection_payload(scope),self.f.lease)
            self.assertEqual(normalize.call_count,1)

    def test_task_preparation_releases_bridge_lock(self):
        from app.learning import tasks
        bridge=self.f.bridge();original=tasks.create_task
        def checked(*args,**kwargs):
            acquired=threading.Event()
            def reader():
                with bridge.lock:acquired.set()
            thread=threading.Thread(target=reader);thread.start()
            self.assertTrue(acquired.wait(3),'read blocked on candidate preparation')
            thread.join();return original(*args,**kwargs)
        with patch.object(tasks,'create_task',side_effect=checked):
            bridge.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))

    def test_failed_job_without_task_can_cancel(self):
        from app.learning.workflows import cancel_job
        bridge=self.f.bridge();bridge.queue_task('summarize_paper','paper-test',str(uuid.uuid4()))
        with bridge.lock:
            job=bridge._workflow_listing()[0]
            self.f.conn.execute("UPDATE workflow_jobs SET status='failed',task_id=NULL WHERE id=?",(job['id'],));self.f.conn.commit()
            from types import SimpleNamespace
            from app.services.task_summary import TaskSummary
            from app.storage.database import Database
            summary=TaskSummary(SimpleNamespace(bridge=bridge,database=Database(__import__('database_fixture').config()))).read()
            self.assertIn('cancel',next(i for i in summary['items'] if i['id']==job['id'])['allowed_actions'])
            cancel_job(self.f.conn,job['id']);self.f.conn.commit()
            self.assertEqual(self.f.conn.execute('SELECT status FROM workflow_jobs WHERE id=?',(job['id'],)).fetchone()[0],'abandoned')

    def test_stopping_during_unlocked_tool_drops_stale_reply(self):
        bridge=self.f.bridge();bridge.submit_task('summarize_paper','paper-test',str(uuid.uuid4()))
        self.f.wait(lambda:bridge._active() and not bridge._active()['codex_turn_id'].startswith('pending-'))
        turn=bridge._active()
        def stop(*args,**kwargs):bridge.interrupt();return []
        with patch('app.agent.tools.execute',side_effect=stop):
            bridge.event(dict(method='item/tool/call',id='stale',params=dict(threadId=turn['session_id'],turnId=turn['codex_turn_id'],tool='mathlens',arguments=dict(action='context',payload={}))))
        self.assertIsNone(bridge._active())

class TargetedTopicsTests(unittest.TestCase):
    def test_topics_stats_only_requested_materials(self):
        from test_knowledge_links import KnowledgeLinksTests
        f=KnowledgeLinksTests();f.setUp();self.addCleanup(f.doCleanups)
        path=f.config.library_dir/'bank-assets/unrelated.bin';path.parent.mkdir(exist_ok=True);path.write_bytes(b'isolated material')
        f.conn.execute("INSERT INTO bank_questions(id,source,stem,created_at) VALUES('unrelated','synthetic','Synthetic','now')")
        f.conn.execute("INSERT INTO bank_resources VALUES('unrelated','{}','bank-assets/unrelated.bin',NULL,NULL)")
        f.conn.commit()
        f.service.summary()
        from app.storage import navigation_index
        original=navigation_index.file_stamp
        with patch.object(navigation_index,'file_stamp',wraps=original) as stat:
            self.assertEqual(len(f.service.topics([f.ids[0]])['items']),1)
            self.assertLessEqual(stat.call_count,6)
            self.assertFalse(any(call.args[0]==path for call in stat.call_args_list))

class ApplicabilityTests(unittest.TestCase):
    def test_backfill_preserves_existing_reviewed_annotation(self):
        from test_knowledge_links import KnowledgeLinksTests
        from test_source_import import question
        from app.bank import annotations,source_records
        from app.bank.applicability import initialize
        f=KnowledgeLinksTests();f.setUp();self.addCleanup(f.doCleanups);bid=f.ids[0]
        before=annotations.current(f.conn,f.f.data,bid)
        rows=[tuple(r) for r in f.conn.execute('SELECT * FROM question_annotations')]
        record=question('synthetic-s03','S03',None);record.update(revision='19f626daefe25fe0e0d76abc30413b697fe4ce24',exam_year=None,math_type=None)
        record['locator']['path']='chapters/chapter-32.html'
        f.conn.execute('INSERT INTO bank_source_records VALUES(?,?,?,?,?,?,?)',(bid,'S03',record['source_uid'],record['revision'],source_records.digest([record,[]]),source_records.canonical(record),'[]'))
        initialize(f.conn);f.conn.commit()
        self.assertEqual(rows,[tuple(r) for r in f.conn.execute('SELECT * FROM question_annotations')])
        self.assertEqual(before,annotations.current(f.conn,f.f.data,bid))

    def test_s03_backfill_is_idempotent_and_book_filter_sort_work(self):
        from test_source_import import SourceImportTests,question
        from app.bank import source_records
        from app.bank.source_import import import_source
        from app.storage.database import Database
        from app.bank.applicability import initialize
        from app.runtime import AppRuntime
        import sqlite3
        f=SourceImportTests();f.setUp();self.addCleanup(f.doCleanups)
        batch=[]
        for n in (10,2,1):
            q=question(str(n),'S03',None);q.update(exam_year=None,math_type=None,number=None,
                revision='19f626daefe25fe0e0d76abc30413b697fe4ce24')
            q['locator']['path']='chapters/chapter-32.html'
            q['book']=dict(title='Synthetic',edition=None,part='强化篇',chapter='Example',number=None,locator='chapters/chapter-32.html#q'+str(n))
            batch.append(q)
        f.batch=batch;f.save()
        plan=import_source(f.config,'S03',f.path,collection='zhangyu-1000')
        import_source(f.config,'S03',f.path,collection='zhangyu-1000',confirm=plan['plan_sha256'])
        with sqlite3.connect(f.config.library_database) as conn:
            rows=list(conn.execute('SELECT id,stem,answer,explanation FROM bank_questions'))
            initialize(conn);initialize(conn)
            self.assertEqual(rows,list(conn.execute('SELECT id,stem,answer,explanation FROM bank_questions')))
        for q in batch:q['math_types']=[1]
        f.save();again=import_source(f.config,'S03',f.path,collection='zhangyu-1000')
        self.assertEqual(len(again['unchanged']),3)
        Database(f.config).initialize();rt=AppRuntime(f.config,agent_factory=None);self.addCleanup(rt.close)
        result=rt.frontend.bank(collection='zhangyu-1000',math_type='1')
        self.assertEqual([v['id'] for v in result['items']],[source_records.bank_id(batch[i]) for i in (2,1,0)])
        self.assertEqual(rt.frontend.bank(collection='zhangyu-1000',math_type='2')['total'],0)
        group=next(v for v in rt.frontend.collections() if v['id']=='zhangyu-1000')
        self.assertEqual(group['math_types'],[dict(math_type=1,total=3,ready=0)])
        for item in result['items']:self.assertEqual(item['math_types'],[1])

    def test_text_without_resource_has_no_broken_image_url(self):
        from app.bank.access import text_resources
        import sqlite3
        conn=sqlite3.connect(':memory:');self.addCleanup(conn.close);conn.row_factory=sqlite3.Row
        conn.execute('CREATE TABLE bank_resources(bank_id TEXT)');conn.execute('CREATE TABLE bank_questions(id TEXT,stem TEXT,explanation TEXT,answer TEXT)')
        conn.execute("INSERT INTO bank_questions VALUES('q','Synthetic','Reference','1')")
        result=text_resources(conn,'q',dict(question_image='/bad',analysis_image='/bad'),reference=True)
        self.assertNotIn('question_image',result);self.assertNotIn('analysis_image',result);self.assertEqual(result['question_text'],'Synthetic')
