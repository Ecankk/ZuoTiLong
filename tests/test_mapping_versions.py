from app.storage.boundaries import workspace_config,connect_workspace
"""Scoped reorganization of real saved evidence, in disposable databases."""
import copy,json,sqlite3,unittest,uuid
from contextlib import closing
from unittest.mock import patch
import database_fixture as server
import test_learning_tasks as fixtures
import test_knowledge_catalog as catalog_fixtures
from app.knowledge import catalog,candidates,mapping_versions as versions
from app.knowledge.index import sources,snapshot
from app.learning.tasks import deliver,finish_task,record_read,receipt,task_package,create_task
from app.learning.workflows import enqueue,init_workflows,guard
from app.learning.workflows import continue_job
from app.services.knowledge import KnowledgeService
from app.config import AppConfig
from app.storage.database import Database

TOPIC='GS-04-001'


class MappingVersionsTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.LearningTaskTests();self.f.setUp();self.conn=self.f.conn
        self.f.fixture.report.update(completion='complete',review={'status':'verified','issues':[]})
        self.f.fixture.apply()
        self.catalog_fixture=catalog_fixtures.KnowledgeCatalogTests();self.catalog_fixture.setUp()
        candidates.import_11408(self.conn,self.catalog_fixture.source)
        self.publish(self.catalog_fixture.value())

    def tearDown(self):
        self.catalog_fixture.tearDown();self.f.tearDown()

    def publish(self,value=None):
        value=value or copy.deepcopy(catalog.document(self.conn)['document'])
        parent=catalog.active_id(self.conn)
        draft=catalog.create_draft(self.conn,value,expected_parent=parent)
        catalog.publish(self.conn,draft['id'],expected_parent=parent,reviewer='isolated-math-review')
        self.conn.commit()

    def change(self,nid,**fields):
        value=copy.deepcopy(catalog.document(self.conn)['document'])
        next(n for n in value['nodes'] if n['id']==nid).update(fields)
        self.publish(value)

    def start(self,scope=None,version='1.8'):
        self.f.start('organize_knowledge',knowledge_request=scope,contract_version=version)
        self.inputs=json.loads(self.f.task['input_json'])
        for item in self.inputs['knowledge_sources']:
            record_read(self.conn,self.f.lease,'knowledge',item['source_id'],'evidence',item['source_revision'])

    def tool(self,payload):
        from app.agent.tools import execute
        self.conn.commit()
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            result=execute(self.f.root,self.f.data,'task_context',payload,lease=self.f.lease)
        return json.loads(result[0]['text'])

    def value(self,topics=None):
        topics=[TOPIC] if topics is None else topics
        return self.f.envelope({'summary':'Associate already saved evidence only.','new_nodes':[],
            'mappings':[{'source_id':s['source_id'],'source_revision':s['source_revision'],
                'topic_ids':topics,'reason':'The recorded mathematical scope supports this concept.',
                'event_topics':[{'event_id':e['id'],'topic_ids':topics[:1]} for e in s['events']]}
                for s in self.inputs['knowledge_sources']], 'limitations':[] if topics else ['No exact supported concept.']})

    def save(self,topics=None,scope=None,version='1.8'):
        self.start(scope,version)
        if version=='1.8' and topics!=[]:self.tool({'topic_ids':topics or [TOPIC]})
        result=deliver(self.conn,self.f.root,self.f.data,self.value(topics),self.f.lease)
        finish_task(self.conn,self.f.task['id']);self.conn.commit();return result

    def unaffected(self):
        return {t:[tuple(r) for r in self.conn.execute('SELECT * FROM '+t)] for t in
                ('agent_reports','questions','question_diagnoses','probe_attempts','learning_events','bank_views','bank_exposures')}

    def test_actual_definition_read_is_required_and_failed_delivery_rolls_back(self):
        self.start();before=self.unaffected()
        query=self.tool({'knowledge_query':{'query':'链式'}})
        self.assertIn(TOPIC,[n['id'] for n in query['items']])
        self.assertNotIn('origin',query['items'][0])
        with self.assertRaisesRegex(ValueError,'knowledge_definition'):
            deliver(self.conn,self.f.root,self.f.data,self.value(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mapping_versions').fetchone()[0],0)
        self.tool({'topic_ids':[TOPIC]})
        deliver(self.conn,self.f.root,self.f.data,self.value(),self.f.lease)
        self.assertEqual(before,self.unaffected())

    def test_saved_version_tracks_math_dependencies_without_regrading(self):
        before=self.unaffected();self.save()
        current=versions.select_sources(self.conn,'paper-test')
        self.assertEqual(current,[])
        record=json.loads(self.conn.execute('SELECT metadata_json FROM knowledge_mapping_versions LIMIT 1').fetchone()[0])
        self.assertEqual(record['rule_revision'],versions.RULE_REVISION)
        self.assertIn(TOPIC,record['dependencies'])
        self.assertIn('math1.calculus.differentiation',record['dependencies'])
        self.assertEqual(before,self.unaffected())
        self.assertEqual(snapshot(self.conn),snapshot(self.conn))

    def test_unrelated_publication_does_not_break_inflight_mapping(self):
        self.start();captured=self.inputs['knowledge_catalog_revision']
        self.change('math1.probability.testing',definition='An unrelated hypothesis-testing scope.')
        read=self.tool({'topic_ids':[TOPIC]})
        self.assertEqual(read['catalog_revision'],captured)
        deliver(self.conn,self.f.root,self.f.data,self.value(),self.f.lease)
        self.assertEqual(versions.select_sources(self.conn,'paper-test'),[])

    def test_related_definition_change_rejects_inflight_result(self):
        self.start();self.tool({'topic_ids':[TOPIC]})
        self.change(TOPIC,conditions=['A changed mathematical condition.'])
        with self.assertRaisesRegex(ValueError,'定义.*变化'):
            deliver(self.conn,self.f.root,self.f.data,self.value(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def test_alias_and_unrelated_definition_changes_reuse_saved_mapping(self):
        self.save();before=self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0]
        self.change(TOPIC,aliases=['链式法则','同一概念的另一个名称'])
        self.change('math1.probability.testing',definition='Another unrelated scope description.')
        self.assertEqual(versions.select_sources(self.conn,'paper-test'),[])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0],before)

    def test_parent_definition_change_invalidates_affected_evidence(self):
        self.save();self.change('math1.calculus.differentiation',definition='Changed differentiation boundary.')
        self.assertEqual(len(versions.select_sources(self.conn,'paper-test')),len(sources(self.conn,'paper-test')))
        self.assertTrue(all(s['reason']=='definition_changed' for s in snapshot(self.conn)['pending_sources']))
        self.assertFalse(any(n['events'] for n in snapshot(self.conn)['nodes']))

    def test_same_definition_redirect_preserves_saved_mapping(self):
        self.save();value=copy.deepcopy(catalog.document(self.conn)['document'])
        node=next(n for n in value['nodes'] if n['id']==TOPIC)
        node['id']='approved-chain-rule';node['name']='复合映射链式导数'
        value['redirects'].append({'old_id':TOPIC,'target_id':node['id'],'reason':'Reviewed equivalent definition.'})
        value['source_resolutions'][0]['node_ids']=[node['id']]
        self.publish(value)
        self.assertEqual(versions.select_sources(self.conn,'paper-test'),[])
        item=next(n for n in snapshot(self.conn)['nodes'] if n['skill_id']==node['id'])
        self.assertEqual(item['failures'],2)

    def test_rule_change_marks_current_mapping_stale_without_falling_back(self):
        self.save();before=self.unaffected()
        with patch.object(versions,'RULE_REVISION','evidence-mapping/next'):
            self.assertTrue(versions.select_sources(self.conn,'paper-test'))
            state=snapshot(self.conn)
            self.assertTrue(all(s['reason']=='rule_changed' for s in state['pending_sources']))
            self.assertFalse(any(n['events'] for n in state['nodes']))
        self.assertEqual(before,self.unaffected())

    def test_unknown_mapping_reconsiders_semantic_expansion_but_not_aliases(self):
        self.save(topics=[])
        self.assertEqual(versions.select_sources(self.conn,'paper-test'),[])
        self.change(TOPIC,aliases=['链式法则','同义词'])
        self.assertEqual(versions.select_sources(self.conn,'paper-test'),[])
        self.change(TOPIC,definition='A revised mathematical definition.')
        self.assertTrue(versions.select_sources(self.conn,'paper-test'))
        self.assertTrue(all(n['failures']==0 for n in snapshot(self.conn)['nodes']))

    def test_explicit_subset_refresh_appends_new_version_and_preserves_other_sources(self):
        self.save();before=self.unaffected();all_ids=[s['source_id'] for s in sources(self.conn,'paper-test')]
        count=self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0]
        self.save(scope={'source_ids':all_ids[:1],'refresh':True})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0],count+1)
        self.assertEqual(versions.select_sources(self.conn,'paper-test'),[])
        self.assertEqual(before,self.unaffected())

    def test_legacy_inflight_task_can_finish_and_is_marked_unversioned(self):
        self.save(version='1.6')
        state=snapshot(self.conn)
        self.assertTrue(any(n['events'] for n in state['nodes']))
        self.assertTrue(all(s['reason']=='legacy_unversioned' for s in state['pending_sources']))
        self.assertTrue(versions.select_sources(self.conn,'paper-test'))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM knowledge_mapping_versions').fetchone()[0],0)

    def test_latest_stale_mapping_does_not_revive_an_older_valid_conclusion(self):
        self.save(topics=['math1.probability.testing'])
        self.save(scope={'source_ids':[s['source_id'] for s in sources(self.conn,'paper-test')],'refresh':True})
        self.change(TOPIC,definition='Different definition after the latest mapping.')
        state=snapshot(self.conn)
        self.assertFalse(any(n['events'] for n in state['nodes']))

    def test_scope_and_query_reject_foreign_ids_or_mixed_read_operations(self):
        with self.assertRaisesRegex(ValueError,'不属于'):
            self.start({'source_ids':['missing-question'],'refresh':True})
        self.start()
        for payload in ({'topic_ids':['not-captured']},{'source_ids':[['bad']]},
                        {'source_ids':['x'],'topic_ids':[TOPIC]},{'knowledge_query':{'limit':True}}):
            with self.subTest(payload=payload),self.assertRaises(ValueError):self.tool(payload)

    def test_service_default_and_explicit_refresh_are_idempotent_and_scope_bound(self):
        self.save();self.conn.commit()
        config=AppConfig(self.f.root,self.f.data,self.f.root/'dist',server.DB_PATH)
        service=KnowledgeService(config,Database(config))
        self.assertEqual(service.organize('paper-test')['jobs'],[])
        sid=sources(self.conn,'paper-test')[0]['source_id'];request=str(uuid.uuid4())
        body={'source_ids':[sid],'refresh':True,'request_id':request}
        one=service.organize('paper-test',body);two=service.organize('paper-test',body)
        self.assertEqual(one['jobs'],two['jobs'])
        with self.assertRaisesRegex(ValueError,'范围'):
            service.organize('paper-test',{**body,'source_ids':[s['source_id'] for s in sources(self.conn,'paper-test')]})

    def test_http_scope_validation_and_queueing_without_creating_session(self):
        self.conn.commit()
        from http_support import client
        with client() as http:
            self.assertEqual(http.post('/api/knowledge/organize',json={'refresh':True}).status_code,400)
            self.assertEqual(http.post('/api/knowledge/organize?paper_id=paper-test',json={'refresh':'yes'}).status_code,400)
            response=http.post('/api/knowledge/organize?paper_id=paper-test',json={})
            self.assertEqual(response.status_code,200,response.text)
            self.assertTrue(response.json()['jobs'])
            job=self.conn.execute('SELECT * FROM workflow_jobs ORDER BY rowid DESC LIMIT 1').fetchone()
            self.assertEqual(job['contract_version'],'1.8');self.assertIsNone(job['task_id'])

    def test_migrated_pending_job_retains_original_contract(self):
        job=enqueue(self.conn,self.f.root,self.f.data,'organize_knowledge','paper-test',str(uuid.uuid4()),contract_version='1.6')
        self.conn.execute('UPDATE workflow_jobs SET contract_version=NULL,index_contract_version=? WHERE id=?',('1.6',job['id']))
        init_workflows(self.conn)
        row=self.conn.execute('SELECT * FROM workflow_jobs WHERE id=?',(job['id'],)).fetchone()
        self.assertEqual(row['contract_version'],'1.6');self.assertIsNone(row['knowledge_json'])
        task=create_task(self.conn,self.f.root,self.f.data,'organize_knowledge','paper-test','old-session',job['request_id'],contract_version=row['contract_version'])
        self.assertEqual(json.loads(task['input_json'])['contract_version'],'1.6')

    def test_restart_preserves_scope_and_guard_without_regrading(self):
        sid=sources(self.conn,'paper-test')[0]['source_id'];scope={'source_ids':[sid],'refresh':True}
        job=enqueue(self.conn,self.f.root,self.f.data,'organize_knowledge','paper-test',str(uuid.uuid4()),knowledge_request=scope)
        self.conn.commit()
        with closing(connect_workspace(workspace_config(self.f.data,self.f.root))) as reopened:
            reopened.row_factory=sqlite3.Row
            row=reopened.execute('SELECT * FROM workflow_jobs WHERE id=?',(job['id'],)).fetchone()
            self.assertEqual(json.loads(row['knowledge_json']),scope)
            self.assertEqual(json.loads(row['guard_json']),guard(reopened,self.f.root,self.f.data,'organize_knowledge','paper-test',knowledge_request=scope))

    def test_changed_source_cannot_be_saved_under_old_input(self):
        self.start();self.tool({'topic_ids':[TOPIC]})
        from app.learning.loop import apply_report
        report=copy.deepcopy(self.f.fixture.report)
        report['questions'][0]['observation']='A new observation in a later report.'
        apply_report(self.conn,'paper-test',report,self.f.root)
        with self.assertRaisesRegex(ValueError,'证据已变化'):
            deliver(self.conn,self.f.root,self.f.data,self.value(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def test_old_queued_continuation_does_not_silently_upgrade_to_18(self):
        self.f.start('prepare_practice',contract_version='1.6')
        job=enqueue(self.conn,self.f.root,self.f.data,'prepare_practice','paper-test',self.f.task['request_id'],
                    index_after=True,index_contract_version='1.6')
        value=self.f.envelope({'goals':[],'exercises':[],'limitations':['No useful exercise in this fixture.']})
        deliver(self.conn,self.f.root,self.f.data,value,self.f.lease)
        finish_task(self.conn,self.f.task['id'])
        task=dict(self.conn.execute('SELECT * FROM learning_tasks WHERE id=?',(self.f.task['id'],)).fetchone())
        continue_job(self.conn,self.f.root,self.f.data,job,task)
        child=self.conn.execute("SELECT * FROM workflow_jobs WHERE kind='organize_knowledge'").fetchone()
        self.assertEqual(child['contract_version'],'1.6');self.assertIsNone(child['knowledge_json'])
