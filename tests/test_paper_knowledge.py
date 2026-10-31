import hashlib
import json
import unittest
import uuid
from unittest.mock import patch

import pymupdf
from app.agent.tools import execute
from app.knowledge import index
from app.knowledge.source_hints import for_sources
from app.learning import tasks, paper_knowledge
from app.learning.contracts import result_schema, validate_result
from app.storage.practice_materials import load
import test_question_annotations as preparation_fixture


class PaperKnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.f = preparation_fixture.QuestionPreparationTests();self.f.setUp()
        self.conn,self.data,self.root = self.f.conn,self.f.data,self.f.root
        self.f.prepare_catalog();ids=self.f.seed_questions(aliases=True)
        for bid in ids:self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',(bid,'{}','',None,None))
        self.conn.commit();self.f.start('annotate_questions',{'bank_ids':ids});self.f.read_annotation_material()
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        tasks.finish_task(self.conn,self.f.task['id']);self.conn.commit()
        folder = self.data/'papers';folder.mkdir(exist_ok=True);self.pdf = folder/'2020math1.pdf'
        with pymupdf.open() as doc:
            page=doc.new_page();page.insert_text((60,60),'1. Differentiate sin(x squared). Student: 2x cos(x squared).');doc.save(self.pdf)
        self.source_sha = hashlib.sha256(self.pdf.read_bytes()).hexdigest()
        self.conn.execute('''INSERT INTO papers(id,title,source_name,source_path,source_sha256,created_at)
            VALUES('paper-test','2020数一','2020math1.pdf',?,?,'now')''',(str(self.pdf),self.source_sha))
        self.conn.execute("INSERT INTO questions(id,paper_id,number,stem,created_at) VALUES('paper-test-q-01','paper-test',1,'OCR draft','now')")
        self.conn.commit();self.task=None

    def tearDown(self):self.f.tearDown()

    def start(self,kind='analyze_paper',**kwargs):
        self.kind=kind
        self.task=tasks.create_task(self.conn,self.root,self.data,kind,'paper-test','same-session',str(uuid.uuid4()),contract_version='2.0',**kwargs)
        tasks.bind_turn(self.conn,self.task['id'],'same-session',self.task['run_token'],'turn-paper')
        self.lease={'task_id':self.task['id'],'session_id':'same-session','run_token':self.task['run_token'],'turn_id':'turn-paper'}
        self.conn.commit();return self.task

    def tool(self,action,payload):return json.loads(execute(self.root,self.data,action,payload,lease=self.lease)[0]['text'])

    def question(self):
        return {'number':1,'subject':'数学一','stem':'求sin(x²)的导数。','max_score':None,'score_earned':None,
            'correctness':'correct','regions':[{'page':1,'bbox':[20,20,550,300],'role':'question_and_work'}],
            'evidence_status':'readable','reference_answer':'2x cos(x²)','reference_reasoning':'链式法则：外层导数cos(x²)乘内层导数2x。',
            'observation':'学生先对外层求导并保留内层导数。','correct_parts':['正确保留内层导数2x。'],'first_error':None,
            'knowledge':['一元复合函数求导'],'fingerprint':{'conditions':['sin(x²)'],'goal':'一阶导数','methods':['链式求导'],'operations':['逐层求导并相乘']},
            'hypotheses':[],'skill_events':[{'skill_id':'chain','label':'链式求导','kind':'exam_success'}],
            'answer_evidence':{'student_work':'2x cos(x²)','student_state':'visible','marking':'none','marking_note':''},
            'solution_guide':{'entry_point':'识别外层sin与内层平方。','strategy':'应用链式法则。','key_steps':['(sin(x²))′=cos(x²)·2x。'],'pitfalls':['不能漏乘内层导数。']},'cause_summary':''}

    def value(self,refs=True):
        entry=json.loads(self.task['input_json'])['paper_knowledge']['entries'][0] if refs else None
        references=[{'number':1,'bank_id':entry['bank_id'],'annotation_id':entry['binding']['annotation_id'],
            'comparison':{'conditions':'原卷和题库均为sin(x²)的一元实函数。','target':'两者均求一阶导数，无参数附加条件。','options_and_figure':'均无图，无选项；函数及求导阶数相同。'}}] if refs else []
        report={'author':'isolated-agent','method':'核原题后验证通用推导并独立检查学生作答。','source_sha256':self.source_sha,
            'expected_count':1,'summary':'链式法则步骤正确。','score_status':'unknown','priorities':[],'limitations':[],
            'questions':[self.question()],'review':{'status':'verified','issues':[]}}
        result={'completion':'complete','report':report,'references':references}
        if self.kind=='review_question':
            result={'completion':'complete','question':self.question(),'review':report['review'],'summary':report['summary'],
                'priorities':[],'resolved_issue_indexes':[],'resolved_limitation_indexes':[],'references':references}
        return {'schema_version':'2.0','task_id':self.task['id'],'kind':self.kind,'paper_id':'paper-test',
            'input_revision':self.task['input_revision'],'author':'isolated-agent','result':result}

    def read(self,original=True,bank=True,definitions=True):
        if original:
            request={'paper_id':'paper-test','pages':[1]}
            if self.kind=='review_question':request['question_id']='paper-test-q-01'
            self.tool('read_paper',request)
        if bank:self.tool('read_bank',{'bank_id':'math1-2020-01','role':'all'})
        if definitions:self.tool('task_context',{'topic_ids':['GS-04-001']})

    def deliver(self,value=None):return self.tool('apply_report',{'result':value or self.value()})

    def test_capture_has_only_ready_current_source_candidates_and_package_is_compact(self):
        self.start();inputs=json.loads(self.task['input_json']);entry=inputs['paper_knowledge']['entries'][0]
        self.assertEqual(entry['bank_id'],'math1-2020-01')
        self.assertEqual(entry['topic_ids'],['GS-04-001'])
        package=tasks.task_package(self.conn,self.task['id'])
        self.assertEqual(package['paper_references']['candidates'][0]['annotation_id'],entry['binding']['annotation_id'])
        self.assertNotIn('reference_reasoning',json.dumps(package['paper_references']))

    def test_read_material_and_actual_definition_are_both_required_before_reuse(self):
        self.start();self.read(bank=False,definitions=False)
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.deliver()
        self.assertIsNone(tasks.receipt(self.conn,self.task['id']))
        self.read(original=False,definitions=False)
        with self.assertRaisesRegex(ValueError,'paper_definition'):self.deliver()
        self.read(original=False,bank=False)
        self.assertIn('result_id',self.deliver())

    def test_reuse_never_replaces_reading_original_work(self):
        self.start();self.read(original=False)
        with self.assertRaisesRegex(ValueError,'paper/'):self.deliver()
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM paper_question_bindings').fetchone()[0],0)

    def test_actual_tools_deliver_fixed_reference_without_creating_additional_student_events(self):
        self.start();self.read();value=self.deliver()
        row=self.conn.execute('SELECT * FROM paper_question_bindings').fetchone()
        payload=json.loads(row['payload_json']);snapshot=payload['binding']
        self.assertEqual(load(self.data,snapshot['snapshot_key'],snapshot['snapshot_sha256'])['bank_id'],'math1-2020-01')
        self.assertEqual(row['report_id'],value['projection']['report_id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM learning_events').fetchone()[0],1)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM probe_attempts').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_views').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_exposures').fetchone()[0],0)

    def test_saved_reference_has_only_relevant_definitions_and_ancestors(self):
        self.start();self.read();self.deliver()
        scope=json.loads(self.task['input_json'])['paper_knowledge'];entry=scope['entries'][0]
        payload=json.loads(self.conn.execute('SELECT payload_json FROM paper_question_bindings').fetchone()[0])
        captured={n['id']:n for n in scope['catalog_nodes']}
        stored={n['id']:n for n in payload['catalog_nodes']}
        self.assertEqual(set(stored),set(entry['dependencies']))
        self.assertTrue(set(captured)-set(stored),'Fixture must contain unrelated knowledge.')
        for tid,value in stored.items():self.assertEqual(value,captured[tid])
        self.assertLess(len(json.dumps(payload['catalog_nodes'])),len(json.dumps(scope['catalog_nodes'])))
        self.assertIn('reference_reasoning',payload['prepared'])

    def test_old_full_catalogue_reference_remains_readable_without_rewriting_it(self):
        self.start();self.read();self.deliver();tasks.finish_task(self.conn,self.task['id']);self.conn.commit()
        row=self.conn.execute('SELECT report_id,question_id,payload_json FROM paper_question_bindings').fetchone()
        payload=json.loads(row['payload_json']);payload['catalog_nodes']=json.loads(self.task['input_json'])['paper_knowledge']['catalog_nodes']
        self.conn.execute('UPDATE paper_question_bindings SET payload_json=? WHERE report_id=? AND question_id=?',
            (json.dumps(payload),row['report_id'],row['question_id']));self.conn.commit()
        before=self.conn.total_changes
        source=next(s for s in index.sources(self.conn,'paper-test') if s['kind']=='question')
        hints=for_sources(self.conn,{'contract_version':'1.8','knowledge_catalog':index.catalog(self.conn)},[source])
        self.assertEqual(hints[0]['question_topics'][0]['id'],'GS-04-001')
        self.assertEqual(self.conn.total_changes,before)

    def test_duplicate_delivery_returns_original_receipt_without_rechecking_its_own_changed_report(self):
        self.start();self.read();payload=self.value();first=self.deliver(payload);again=self.deliver(payload)
        self.assertEqual(first['result_id'],again['result_id']);self.assertTrue(again['reused'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM paper_question_bindings').fetchone()[0],1)

    def test_unreadable_original_cannot_be_linked_even_with_known_reference(self):
        self.start();self.read();value=self.value()
        value['result']['report']['questions'][0]['evidence_status']='unclear'
        with self.assertRaisesRegex(ValueError,'原题题意'):self.deliver(value)

    def test_out_of_scope_question_number_or_annotation_is_rejected(self):
        self.start();self.read()
        for field,value in [('number',2),('annotation_id','different'),('bank_id','math2-2019-01')]:
            payload=self.value();payload['result']['references'][0][field]=value
            with self.assertRaises(ValueError):self.deliver(payload)
        payload=self.value();payload['result']['references']*=2
        with self.assertRaisesRegex(ValueError,'最多关联'):self.deliver(payload)

    def test_changed_reference_does_not_block_independent_analysis_with_empty_references(self):
        self.start();self.read();self.conn.execute("UPDATE bank_questions SET answer='changed' WHERE id='math1-2020-01'");self.conn.commit()
        with self.assertRaisesRegex(ValueError,'参考材料已变化'):self.deliver()
        value=self.deliver(self.value(refs=False))
        self.assertIn('report_id',value['projection'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM paper_question_bindings').fetchone()[0],0)

    def test_task_context_reads_only_captured_prepared_candidate(self):
        self.start();before=self.conn.execute('SELECT COUNT(*) FROM bank_views').fetchone()[0]
        value=self.tool('task_context',{'bank_ids':['math1-2020-01']})
        self.assertIn('reference_reasoning',value['paper_references'][0]['prepared_question'])
        with self.assertRaisesRegex(ValueError,'捕获'):self.tool('task_context',{'bank_ids':['math2-2019-01']})
        with self.assertRaisesRegex(ValueError,'source_ids'):self.tool('task_context',{'source_ids':['paper-test-q-01']})
        with self.assertRaisesRegex(ValueError,'分别读取'):self.tool('task_context',{'bank_ids':['math1-2020-01'],'topic_ids':['GS-04-001']})
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM bank_views').fetchone()[0],before)

    def test_original_pdf_change_rejects_result_even_without_reference(self):
        self.start();self.read();self.pdf.write_bytes(self.pdf.read_bytes()+b'\nchanged')
        with self.assertRaisesRegex(ValueError,'证据已变化'):self.deliver(self.value(refs=False))

    def test_retry_freezes_old_reference_input_and_rekeys_read_evidence(self):
        self.start();self.read();original=self.task['input_json']
        tasks.fail_task(self.conn,self.task['id'],'isolated disconnect');self.conn.commit()
        task=tasks.retry_task(self.conn,self.root,self.data,self.task['id'])
        self.assertEqual(task['input_json'],original)
        self.assertNotEqual(task['run_token'],self.task['run_token'])
        tasks.bind_turn(self.conn,task['id'],'same-session',task['run_token'],'turn-retry');self.conn.commit()
        self.task=task;self.lease.update(run_token=task['run_token'],turn_id='turn-retry')
        self.assertIn('result_id',self.deliver())

    def test_report_events_result_and_reference_roll_back_together(self):
        self.start();self.read()
        with patch('app.storage.practice_materials.freeze',side_effect=ValueError('isolated freeze failure')):
            with self.assertRaisesRegex(ValueError,'isolated freeze'):self.deliver()
        for table in ('agent_reports','question_diagnoses','learning_events','paper_question_bindings'):
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
        self.assertIsNone(tasks.receipt(self.conn,self.task['id']))
        self.assertIn('result_id',self.deliver())

    def test_existing_question_hint_reuses_fixed_ids_without_writing_mapping_or_mastery(self):
        self.start();self.read();self.deliver();tasks.finish_task(self.conn,self.task['id']);self.conn.commit()
        source=next(s for s in index.sources(self.conn,'paper-test') if s['kind']=='question')
        before=self.conn.total_changes
        hints=for_sources(self.conn,{'contract_version':'1.8','knowledge_catalog':index.catalog(self.conn)},[source])
        self.assertEqual(hints[0]['question_topics'][0]['id'],'GS-04-001')
        self.assertEqual(hints[0]['source_revision'],source['source_revision'])
        self.assertEqual(self.conn.total_changes,before)
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM knowledge_mappings').fetchone()[0],0)

    def test_review_retains_previous_reference_history_and_creates_a_new_binding(self):
        self.start();self.read();first=self.deliver();tasks.finish_task(self.conn,self.task['id']);self.conn.commit()
        self.start('review_question',review_request={'question_id':'paper-test-q-01','report_id':first['projection']['report_id']})
        self.read();second=self.deliver()
        self.assertNotEqual(first['projection']['report_id'],second['projection']['report_id'])
        self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM paper_question_bindings').fetchone()[0],2)

    def test_old_contract_stays_unchanged_and_new_reference_requires_explicit_version(self):
        self.assertNotIn('references',result_schema('analyze_paper','1.6')['properties']['result']['properties'])
        for kind in ('prepare_practice','grade_attempt','organize_knowledge','summarize_paper'):
            with self.assertRaises(ValueError):result_schema(kind,'2.0')
        self.start();value=self.value();value['result'].pop('references')
        with self.assertRaisesRegex(ValueError,'结构不合法'):validate_result(value,'analyze_paper')

    def test_unlocated_paper_can_read_catalogue_and_complete_independently(self):
        self.conn.execute("UPDATE papers SET title='2026数一',source_name='2026math1.pdf' WHERE id='paper-test'");self.conn.commit()
        self.start()
        self.assertEqual(json.loads(self.task['input_json'])['paper_knowledge']['entries'],[])
        self.read(bank=False)
        self.assertIn('report_id',self.deliver(self.value(refs=False))['projection'])

    def test_mutated_annotation_does_not_masquerade_as_captured_version(self):
        self.start();self.read()
        entry=json.loads(self.task['input_json'])['paper_knowledge']['entries'][0]
        row=self.conn.execute('SELECT payload_json FROM question_annotations WHERE id=?',(entry['binding']['annotation_id'],)).fetchone()
        payload=json.loads(row[0]);payload['reference_reasoning']+=' changed'
        self.conn.execute('UPDATE question_annotations SET payload_json=? WHERE id=?',(json.dumps(payload),entry['binding']['annotation_id']));self.conn.commit()
        with self.assertRaisesRegex(ValueError,'参考出处已变化'):self.deliver()
        self.assertIsNone(tasks.receipt(self.conn,self.task['id']))

    def test_fixed_reference_hint_requires_the_original_20_result_proof(self):
        self.start();self.read();value=self.deliver();tasks.finish_task(self.conn,self.task['id']);self.conn.commit()
        source=next(s for s in index.sources(self.conn,'paper-test') if s['kind']=='question')
        row=self.conn.execute('SELECT payload_json FROM learning_results WHERE id=?',(value['result_id'],)).fetchone()
        payload=json.loads(row[0]);payload['result']['references']=[]
        self.conn.execute('UPDATE learning_results SET payload_json=? WHERE id=?',(json.dumps(payload),value['result_id']))
        self.assertEqual(for_sources(self.conn,{'contract_version':'1.8','knowledge_catalog':index.catalog(self.conn)},[source]),[])

    def test_failure_on_second_reference_rolls_back_first_binding_and_whole_report(self):
        bid='math1-2020-02'
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at) SELECT ?,source,stem,answer,explanation,created_at FROM bank_questions WHERE id='math1-2020-01'",(bid,))
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',(bid,'{}','',None,None))
        from app.bank.access import init_access
        init_access(self.conn);self.conn.commit()
        self.f.start('annotate_questions',{'bank_ids':[bid]});self.f.read_annotation_material()
        self.f.tool('apply_report',{'result':self.f.envelope(self.f.annotation_result())})
        tasks.finish_task(self.conn,self.f.task['id']);self.conn.commit()
        self.conn.execute("INSERT INTO questions(id,paper_id,number,stem,created_at) VALUES('paper-test-q-02','paper-test',2,'second independent work','now')");self.conn.commit()
        self.start();self.read();self.tool('read_bank',{'bank_id':bid,'role':'all'})
        value=self.value();report=value['result']['report'];report['expected_count']=2
        report['questions'].append({**self.question(),'number':2})
        entry=next(e for e in json.loads(self.task['input_json'])['paper_knowledge']['entries'] if e['number']==2)
        value['result']['references'].append({**value['result']['references'][0],
            'number':2,'bank_id':bid,'annotation_id':entry['binding']['annotation_id']})
        from app.storage.practice_materials import freeze
        calls=[]
        def failing(*args):
            calls.append(True)
            if len(calls)==2:raise ValueError('second reference failed')
            return freeze(*args)
        with patch('app.storage.practice_materials.freeze',side_effect=failing):
            with self.assertRaisesRegex(ValueError,'second reference'):self.deliver(value)
        self.assertEqual(len(calls),2)
        for table in ('paper_question_bindings','agent_reports','question_diagnoses','learning_events'):
            self.assertEqual(self.conn.execute('SELECT COUNT(*) FROM '+table).fetchone()[0],0,table)
        self.assertIsNone(tasks.receipt(self.conn,self.task['id']))
        self.assertIn('result_id',self.deliver(value))


if __name__=='__main__':unittest.main()
