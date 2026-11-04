"""Initial role methods/evidence and one consistent tool delivery boundary."""
import copy,json,unittest
from unittest.mock import patch
from jsonschema import Draft202012Validator
from app.agent.material_package import initial_inputs
from app.agent.tools import execute,SCHEMA,SKILLS
from app.learning.tasks import receipt
import database_fixture as server

class ExecutionMaterialTests(unittest.TestCase):
    def test_organize_has_methods_complete_event_manifest_and_zero_read_delivery(self):
        from test_mapping_versions import MappingVersionsTests,TOPIC
        from app.learning.loop import apply_report
        case=MappingVersionsTests();case.setUp();self.addCleanup(case.tearDown)
        report=copy.deepcopy(case.f.fixture.report)
        for q in report['questions']:q['knowledge']=[TOPIC]
        apply_report(case.conn,'paper-test',report,case.f.root);case.conn.commit()
        case.start();task=case.f.task;lease=case.f.lease
        case.conn.execute('DELETE FROM task_reads WHERE task_id=?',(task['id'],))
        packet=initial_inputs(case.conn,case.f.root,case.f.data,task['id'],lease);case.conn.commit()
        self.assertFalse(any(i['type']=='localImage' for i in packet))
        header=json.loads(packet[0]['text']);self.assertTrue(header['materials_complete'])
        self.assertNotIn('task',header)
        self.assertLess(len(header['definitions']),len(case.inputs['knowledge_catalog']))
        self.assertIn(TOPIC,{n['id'] for n in header['definitions']})
        self.assertEqual(header['role_method']['skill_names'],['mathlens-knowledge-index'])
        self.assertEqual(header['role_method']['skills'][0]['instructions'],
            (case.f.root/'.agents/skills/mathlens-knowledge-index/SKILL.md').read_text(encoding='utf-8'))
        self.assertEqual([m['event_ids'] for m in header['evidence_manifest']],
            [[e['id'] for e in s['events']] for s in case.inputs['knowledge_sources']])
        template=header['result_template']['result']['mappings']
        self.assertEqual([[v['event_id'] for v in m['event_topics']] for m in template],
            [m['event_ids'] for m in header['evidence_manifest']])
        value=case.value();before=case.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0]
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            valid=json.loads(execute(case.f.root,case.f.data,'preflight',{'result':value},lease=lease)[0]['text'])
            self.assertTrue(valid['valid']);self.assertIsNone(receipt(case.conn,task['id']))
            self.assertEqual(case.conn.execute('SELECT count(*) FROM knowledge_mappings').fetchone()[0],before)
            saved=json.loads(execute(case.f.root,case.f.data,'deliver_result',{'result':value},lease=lease)[0]['text'])
        self.assertIn('result_id',saved)

    def test_review_package_has_all_receipts_and_keeps_parent_summary(self):
        from test_paper_knowledge import PaperKnowledgeTests
        case=PaperKnowledgeTests();case.setUp();self.addCleanup(case.tearDown)
        case.start();case.read();parent=case.deliver();case.conn.commit()
        parent_summary=json.loads(case.conn.execute('SELECT report_json FROM agent_reports WHERE id=?',(parent['projection']['report_id'],)).fetchone()[0])['summary']
        case.start('review_question',review_request={'question_id':'paper-test-q-01','report_id':parent['projection']['report_id']})
        self.assertEqual(case.conn.execute('SELECT count(*) FROM task_reads WHERE task_id=?',(case.task['id'],)).fetchone()[0],0)
        packet=initial_inputs(case.conn,case.root,case.data,case.task['id'],case.lease);case.conn.commit()
        header=json.loads(packet[0]['text']);self.assertTrue(header['materials_complete'])
        self.assertEqual(header['role_method']['skill_names'],['mathlens-paper-diagnosis'])
        self.assertTrue(any(i['type']=='localImage' for i in packet))
        self.assertTrue({'paper','paper_bank','paper_reference','paper_definition','question_review'}.issubset({r['kind'] for r in header['read_receipts']}))
        value=case.value();value['result']['summary']='本题独立复核的结论。'
        self.assertTrue(case.tool('preflight',{'result':value})['valid'])
        self.assertIsNone(receipt(case.conn,case.task['id']))
        saved=case.tool('deliver_result',{'result':value})
        report=json.loads(case.conn.execute('SELECT report_json FROM agent_reports WHERE id=?',(saved['projection']['report_id'],)).fetchone()[0])
        self.assertEqual(report['summary'],parent_summary)
        local=json.loads(case.conn.execute('SELECT payload_json FROM learning_results WHERE id=?',(saved['result_id'],)).fetchone()[0])
        self.assertEqual(local['result']['summary'],'本题独立复核的结论。')
        from app.runtime import AppRuntime
        runtime=AppRuntime(case.f.f.config,agent_factory=None);self.addCleanup(runtime.close)
        self.assertEqual(runtime.frontend.paper('paper-test')['analysis']['summary'],parent_summary)

    def test_tool_schema_and_runtime_share_wrapped_delivery_shape(self):
        payload={'schema_version':'1.8','task_id':'test','result':{}}
        validator=Draft202012Validator(SCHEMA)
        for action in ('preflight','deliver_result'):
            self.assertEqual(list(validator.iter_errors({'action':action,'payload':{'result':payload}})),[])
            self.assertTrue(list(validator.iter_errors({'action':action,'payload':payload})))
            with self.assertRaisesRegex(ValueError,'payload必须为'):
                execute(None,None,action,payload)
        for bad in ({},{'kind':'organize_knowledge'},{'name':'organize_knowledge'},{'name':'question-review'}):
            with self.assertRaises(ValueError) as error:execute(None,None,'read_skill',bad)
            for name in SKILLS:self.assertIn('mathlens-'+name,str(error.exception))

    def test_catalog_unknown_parameter_is_actionable(self):
        from test_mapping_versions import MappingVersionsTests
        case=MappingVersionsTests();case.setUp();self.addCleanup(case.tearDown)
        case.start();case.conn.commit()
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            with self.assertRaisesRegex(ValueError,'catalog可用参数'):
                execute(case.f.root,case.f.data,'catalog',{'query':'example'},lease=case.f.lease)
