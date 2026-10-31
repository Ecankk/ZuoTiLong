from app.storage.boundaries import workspace_config,connect_workspace
import copy
import json
import unittest
import database_fixture as server
import test_learning_tasks as fixtures
from app.knowledge.index import sources, pending_sources, snapshot, catalog
from app.learning.tasks import record_read, deliver, finish_task, receipt
from app.learning.loop import apply_report, submit_probe, assess_attempt, supplement_attempt
from app.services.papers import set_paper_archive

TOPIC='math1.calculus.multiple-integrals'


class KnowledgeIndexTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LearningTaskTests();self.f.setUp();self.conn=self.f.conn
        self.f.fixture.report.update(completion='complete',review={'status':'verified','issues':[]})
        # Performance wording must never become the canonical knowledge name.
        for q in self.f.fixture.report['questions']:
            q['skill_events'][0]['label']='终值与复核结果不符'
        self.f.fixture.apply()

    def tearDown(self):self.f.tearDown()

    def start(self):
        self.f.start('organize_knowledge',contract_version='1.6')
        self.inputs=json.loads(self.f.task['input_json'])
        for source in self.inputs['knowledge_sources']:
            record_read(self.conn,self.f.lease,'knowledge',source['source_id'],'evidence',source['source_revision'])

    def payload(self):
        mappings=[{'source_id':s['source_id'],'source_revision':s['source_revision'],
            'topic_ids':[TOPIC],'reason':'The saved assignment concerns integration regions.',
            'event_topics':[{'event_id':e['id'],'topic_ids':[TOPIC]} for e in s['events']]}
            for s in self.inputs['knowledge_sources']]
        return self.f.envelope({'summary':'Indexed saved evidence only.','new_nodes':[],
                                'mappings':mappings,'limitations':[]})

    def save(self):
        self.start();value=deliver(self.conn,self.f.root,self.f.data,self.payload(),self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit();return value

    def node(self):return next(n for n in snapshot(self.conn)['nodes'] if n['skill_id']==TOPIC)

    def test_stable_names_merge_evidence_without_rewriting_originals(self):
        before={t:[tuple(r) for r in self.conn.execute('SELECT * FROM '+t)] for t in ('agent_reports','questions','learning_events','probe_attempts')}
        self.save();item=self.node()
        self.assertEqual(item['label'],'重积分');self.assertEqual(item['failures'],2)
        self.assertEqual(len(item['question_ids']),2)
        self.assertEqual(sum(s['source_id']=='paper-test-probe-test' for s in item['scopes']),1)
        self.assertEqual(item['probe_ids'],[])  # legacy report is not an active verified plan
        self.assertEqual(item['state'],'需要关注')
        self.assertNotIn('终值与复核结果不符',[n['label'] for n in snapshot(self.conn)['nodes']])
        for table,rows in before.items():self.assertEqual(rows,[tuple(r) for r in self.conn.execute('SELECT * FROM '+table)])
        changes=self.conn.total_changes
        self.assertEqual(snapshot(self.conn),snapshot(self.conn));self.assertEqual(self.conn.total_changes,changes)

    def test_unmapped_evidence_is_pending_not_a_guess_from_labels(self):
        state=snapshot(self.conn)
        self.assertEqual(len(state['pending_sources']),3)
        self.assertTrue(all(not n['events'] and n['state']=='未覆盖' for n in state['nodes']))

    def test_old_mapping_becomes_inactive_when_report_changes(self):
        self.save();old_count=self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0]
        report=copy.deepcopy(self.f.fixture.report);report['questions'][0]['observation']='New interpretation of actual work'
        apply_report(self.conn,'paper-test',report,self.f.root)
        self.assertTrue(pending_sources(self.conn));self.assertEqual(self.node()['failures'],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0],old_count)

    def test_archive_hides_current_profile_and_restore_uses_same_evidence(self):
        self.save();before=self.node()
        set_paper_archive(self.conn,'paper-test',True,True)
        self.assertEqual(snapshot(self.conn)['pending_sources'],[])
        self.assertTrue(all(not n['events'] for n in snapshot(self.conn)['nodes']))
        set_paper_archive(self.conn,'paper-test',False,True)
        self.assertEqual(self.node(),before)

    def test_repeated_raw_labels_count_a_question_once(self):
        report=copy.deepcopy(self.f.fixture.report)
        for q in report['questions']:q['skill_events'].append({'skill_id':'another-id','label':'also a consequence','kind':'exam_error'})
        apply_report(self.conn,'paper-test',report,self.f.root);self.save()
        self.assertEqual(self.node()['failures'],2)

    def test_unknown_or_incomplete_evidence_never_becomes_a_failure(self):
        report=copy.deepcopy(self.f.fixture.report)
        for q in report['questions']:q['skill_events'][0]['kind']='incomplete'
        apply_report(self.conn,'paper-test',report,self.f.root);self.save()
        self.assertEqual(self.node()['failures'],0);self.assertEqual(self.node()['state'],'证据不足')

    def test_partial_success_does_not_claim_mastery_of_whole_chapter(self):
        from app.knowledge.profile import aggregate
        events=[{'id':str(i),'paper_id':f'paper-{i}','question_id':f'q-{i}','source':'exam',
                 'kind':'exam_success','verified':True,'created_at':f'2026-10-{20+i}'} for i in (1,2)]
        for level,expected in [('subject','巩固中'),('chapter','巩固中'),('concept','初步掌握')]:
            with self.subTest(level=level):
                item={'scope_level':level,'events':events,'scopes':[{'paper_id':'paper-1'}],
                      'probe_ids':[],'question_ids':[]}
                aggregate(item);self.assertEqual(item['state'],expected)

    def test_assisted_work_keeps_independent_error_and_single_attempt(self):
        aid=submit_probe(self.conn,'paper-test-probe-test',{'response':'wrong reasoning'})['attempt_id']
        assess_attempt(self.conn,aid,{'correct':False,'feedback':'visible error','author':'agent'})
        self.conn.execute("INSERT INTO bank_exposures VALUES('bank-test','now')")
        supplement_attempt(self.conn,aid,{'response':'revised using the solution'})
        assess_attempt(self.conn,aid,{'correct':True,'feedback':'assisted reasoning is valid','author':'agent'})
        self.save();item=self.node()
        self.assertEqual(item['attempt_count'],1);self.assertEqual(item['assisted_successes'],1)
        self.assertEqual(item['independent_probe_successes'],0);self.assertEqual(item['failures'],3)

    def test_fabricated_event_and_omitted_source_roll_back_entire_result(self):
        self.start();value=self.payload();value['result']['mappings'][0]['event_topics'].append({'event_id':'invented','topic_ids':[TOPIC]})
        with self.assertRaisesRegex(ValueError,'表现证据'):deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0],0)
        value=self.payload();value['result']['mappings'].pop()
        with self.assertRaisesRegex(ValueError,'全部'):deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)

    def test_reading_current_evidence_and_matching_revision_are_required(self):
        self.start();self.conn.execute('DELETE FROM task_reads')
        with self.assertRaisesRegex(ValueError,'尚未读取'):deliver(self.conn,self.f.root,self.f.data,self.payload(),self.f.lease)
        for source in self.inputs['knowledge_sources']:record_read(self.conn,self.f.lease,'knowledge',source['source_id'],'evidence',source['source_revision'])
        value=self.payload();value['result']['mappings'][0]['source_revision']='0'*64
        with self.assertRaisesRegex(ValueError,'过期'):deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)

    def test_routine_indexing_cannot_create_concepts_even_with_real_support(self):
        self.start();value=self.payload()
        node={'id':TOPIC+'.regions','parent_id':TOPIC,'name':'二重积分的积分区域','aliases':['积分区域表示'],
              'reason':'A stable mathematical concept supported by the original tasks.',
              'source_ids':[next(s['source_id'] for s in self.inputs['knowledge_sources'] if s['kind']=='question')]}
        before={table:[tuple(row) for row in self.conn.execute('SELECT * FROM '+table)]
                for table in ('knowledge_nodes','knowledge_mappings','learning_results','learning_events')}
        for name in ('二重积分的积分区域','二重积分区域的表示'):
            with self.subTest(name=name):
                candidate=copy.deepcopy(value)
                candidate['result']['new_nodes']=[{**node,'name':name}]
                with self.assertRaisesRegex(ValueError,'统一知识目录'):
                    deliver(self.conn,self.f.root,self.f.data,candidate,self.f.lease)
                self.assertIsNone(receipt(self.conn,self.f.task['id']))
                for table,rows in before.items():
                    self.assertEqual(rows,[tuple(row) for row in self.conn.execute('SELECT * FROM '+table)])
        # Repair the same task without changing its session or ticket.
        deliver(self.conn,self.f.root,self.f.data,self.payload(),self.f.lease)
        self.assertIsNotNone(receipt(self.conn,self.f.task['id']))

    def test_existing_catalog_concepts_remain_usable_without_recreating_them(self):
        node=TOPIC+'.regions'
        self.conn.execute('INSERT INTO knowledge_nodes VALUES(?,?,?,?,?,?)',
            (node,TOPIC,'二重积分的积分区域',json.dumps(['积分区域表示']),
             json.dumps({'catalog_version':'approved-fixture-v1'}),'2026-10-27'))
        self.start();value=self.payload()
        for mapping in value['result']['mappings']:
            mapping['topic_ids']=[node]
            for event in mapping['event_topics']:event['topic_ids']=[node]
        before=[tuple(row) for row in self.conn.execute('SELECT * FROM knowledge_nodes')]
        deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        self.assertEqual(before,[tuple(row) for row in self.conn.execute('SELECT * FROM knowledge_nodes')])
        item=next(n for n in snapshot(self.conn)['nodes'] if n['skill_id']==node)
        self.assertEqual(item['label'],'二重积分的积分区域')
        self.assertEqual(item['failures'],2)

    def test_unknown_id_is_rejected_instead_of_becoming_an_implicit_node(self):
        self.start();value=self.payload()
        value['result']['mappings'][0]['topic_ids']=['unregistered-concept']
        with self.assertRaisesRegex(ValueError,'不存在的稳定考点'):
            deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertNotIn('unregistered-concept',{n['id'] for n in catalog(self.conn)})

    def test_catalog_gap_can_be_saved_as_unknown_without_creating_nodes(self):
        self.start();value=self.payload()
        for mapping in value['result']['mappings']:
            mapping['topic_ids']=[]
            for event in mapping['event_topics']:event['topic_ids']=[]
        value['result']['limitations']=['The supplied catalog has no sufficiently precise approved concept.']
        before=[tuple(row) for row in self.conn.execute('SELECT * FROM knowledge_nodes')]
        deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        self.assertEqual(before,[tuple(row) for row in self.conn.execute('SELECT * FROM knowledge_nodes')])
        self.assertEqual(pending_sources(self.conn),[])  # legacy source-only capture remains compatible
        self.assertEqual({s['reason'] for s in snapshot(self.conn)['pending_sources']},{'legacy_unversioned'})
        self.assertTrue(all(n['state']=='未覆盖' for n in snapshot(self.conn)['nodes']))

    def test_existing_action_reads_sources_without_new_session_or_tool_name(self):
        from unittest.mock import patch
        from app.agent.tools import execute
        self.start();self.conn.commit();sid=self.inputs['knowledge_sources'][0]['source_id']
        from app.learning.tasks import task_package
        self.assertEqual(task_package(self.conn,self.f.task['id'])['catalog_policy']['mode'],
                         'reference_existing_only')
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            output=execute(self.f.root,self.f.data,'task_context',{'source_ids':[sid]},lease=self.f.lease)
            self.assertEqual(json.loads(output[0]['text'])['sources'][0]['source_id'],sid)
            output=execute(self.f.root,self.f.data,'read_skill',{'name':'knowledge-index'},lease=self.f.lease)
            self.assertIn('instructions',json.loads(output[0]['text']))

    def test_backup_restore_keeps_canonical_ids_and_same_evidence_counts(self):
        import sqlite3
        from pathlib import Path
        from contextlib import closing
        from app.storage.maintenance import backup,restore
        self.save();before=self.node()
        archive=backup(self.f.data,self.f.root)['path']
        destination=self.f.data/'restored-knowledge'
        restore(archive,destination)
        with closing(connect_workspace(workspace_config(destination),library_write=True)) as conn:
            conn.row_factory=sqlite3.Row
            after=next(n for n in snapshot(conn)['nodes'] if n['skill_id']==TOPIC)
        self.assertEqual(before,after)
