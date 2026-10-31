import copy
import json
import unittest
import uuid
from app.agent.tools import execute
from app.bank import annotations
from app.bank.access import init_access, save_preferences
from app.knowledge import catalog
from app.learning.tasks import create_task, bind_turn, deliver, finish_task, receipt, task_package
from app.learning.workflows import enqueue, listing


class QuestionPreparationTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_catalog import KnowledgeCatalogTests
        self.f = KnowledgeCatalogTests();self.f.setUp()
        self.conn = self.f.conn;self.data = self.f.data;self.root = self.f.config.root
        self.task = None;self.lease = None

    def tearDown(self):self.f.tearDown()

    def start(self, kind, scope):
        self.task = create_task(self.conn,self.root,self.data,kind,None,'same-session',str(uuid.uuid4()),task_scope=scope)
        bind_turn(self.conn,self.task['id'],'same-session',self.task['run_token'],'turn-test')
        self.conn.commit()
        self.lease = {'task_id':self.task['id'],'session_id':'same-session','run_token':self.task['run_token'],'turn_id':'turn-test'}

    def tool(self, action, payload):return json.loads(execute(self.root,self.data,action,payload,lease=self.lease)[0]['text'])

    def envelope(self, result):
        return {'schema_version':'1.7','task_id':self.task['id'],'kind':self.task['kind'],'paper_id':None,
                'input_revision':self.task['input_revision'],'author':'isolated-preparation','result':result}

    def maintenance_result(self):
        value = self.f.value()
        return {'summary':'Normalize the chain-rule concept.','node_changes':[value['nodes'][-1]],'redirects':[],
                'source_resolutions':[{k:v for k,v in row.items() if k!='source_version_id'} for row in value['source_resolutions']],
                'limitations':[]}

    def prepare_catalog(self):
        self.start('maintain_catalog',{'source_version_id':self.f.sid,'source_ids':['GS-04-001']})
        self.tool('task_context',{'source_ids':['GS-04-001']})
        result=self.tool('apply_report',{'result':self.envelope(self.maintenance_result())})
        finish_task(self.conn,self.task['id']);self.conn.commit()
        return result

    def seed_questions(self, aliases=False):
        ids=['math1-2020-01']+(['math2-2019-01'] if aliases else [])
        for bid in ids:
            self.conn.execute('''INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at)
                VALUES(?,?,?,?,?,'now')''',(bid,'isolated-synthetic','求 f(x)=sin(x²) 的导数。','2x cos(x²)','外层sin求导，再乘内层x²的导数2x。'))
        init_access(self.conn)
        if aliases:self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)',(*ids,'已确认同题；本隔离样本题干、条件、参考内容完全相同。'))
        self.conn.commit();return ids

    def annotation_result(self, status='ready'):
        source=json.loads(self.task['input_json'])['bank_questions'][0]
        question={'bank_id':source['bank_id'],'content_revision':source['content_revision'],
            'material_revision':source['material_revision'],'status':status,
            'reference_reasoning':'设u=x²，f=sin u，因此df/dx=cos(u)·du/dx=2x cos(x²)。',
            'answer_check':{'status':'consistent','note':'独立推导与参考导数相同。'},
            'bindings':[{'topic_id':'GS-04-001','role':'primary','evidence':'对外层sin与内层平方应用链式求导。','stages':['formula','calculation']}],
            'methods':['链式求导'],'checkpoints':[{'stage':'formula','description':'指出内外函数并写出内层导数。'}],
            'fingerprint':{'conditions':['sin(x²)'],'goal':'求一阶导数','methods':['链式求导'],'operations':['逐层求导并相乘']},
            'unmatched_topics':[],'limitations':[]}
        if status!='ready':question.update(bindings=[],unmatched_topics=['需要的原子尚未核准。'])
        return {'summary':'Saved reusable question knowledge.','questions':[question],'limitations':[]}

    def read_annotation_material(self):
        inputs=json.loads(self.task['input_json'])
        self.tool('read_bank',{'bank_id':inputs['bank_questions'][0]['bank_id'],'role':'all'})
        self.tool('task_context',{'topic_ids':['GS-04-001']})

    def save_annotation(self):
        self.prepare_catalog();ids=self.seed_questions(aliases=True)
        self.start('annotate_questions',{'bank_ids':ids})
        self.read_annotation_material();result=self.annotation_result()
        self.tool('apply_report',{'result':self.envelope(result)})
        finish_task(self.conn,self.task['id']);self.conn.commit()
        return ids

    def test_catalogue_task_reuses_existing_receipt_and_never_creates_student_paper(self):
        result=self.prepare_catalog()
        self.assertIsNotNone(result['projection']['catalog_revision'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM papers').fetchone()[0],0)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM learning_events').fetchone()[0],0)
        self.assertIsNone(self.task['paper_id'])

    def test_maintenance_requires_actual_source_reads_and_repairs_same_task(self):
        self.start('maintain_catalog',{'source_version_id':self.f.sid,'source_ids':['GS-04-001']})
        value=self.envelope(self.maintenance_result())
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.tool('apply_report',{'result':value})
        self.assertIsNone(catalog.active_id(self.conn));self.assertIsNone(receipt(self.conn,self.task['id']))
        self.tool('task_context',{'source_ids':['GS-04-001']})
        first=self.tool('apply_report',{'result':value})
        again=self.tool('apply_report',{'result':value})
        self.assertEqual(first['result_id'],again['result_id']);self.assertTrue(again['reused'])

    def test_annotation_needs_actual_material_and_definition_reads(self):
        self.prepare_catalog();ids=self.seed_questions()
        self.start('annotate_questions',{'bank_ids':ids});value=self.envelope(self.annotation_result())
        with self.assertRaisesRegex(ValueError,'尚未读取'):self.tool('apply_report',{'result':value})
        self.read_annotation_material();self.tool('apply_report',{'result':value})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],1)

    def test_confirmed_same_question_is_analyzed_once_and_reused_without_student_events(self):
        ids=self.save_annotation()
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],1)
        self.assertEqual(annotations.current(self.conn,self.data,ids[0])['id'],annotations.current(self.conn,self.data,ids[1])['id'])
        selected=annotations.search(self.conn,self.data,topic_ids=['math1.calculus.differentiation'],stages=['formula'])
        self.assertEqual(selected['total'],1);self.assertEqual(selected['items'][0]['alternate_bank_ids'],ids)
        for table in ('probe_attempts','learning_events','bank_views','bank_exposures'):
            self.assertEqual(self.conn.execute('SELECT count(*) FROM '+table).fetchone()[0],0)

    def test_unknown_topic_id_rolls_back_entire_delivery(self):
        self.prepare_catalog();ids=self.seed_questions()
        self.start('annotate_questions',{'bank_ids':ids});self.read_annotation_material()
        value=self.annotation_result();value['questions'][0]['bindings'][0]['topic_id']='invented.atomic-concept'
        with self.assertRaisesRegex(ValueError,'未知ID'):self.tool('apply_report',{'result':self.envelope(value)})
        self.assertIsNone(receipt(self.conn,self.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],0)

    def test_changed_material_rejects_old_task_and_invalidates_existing_cache(self):
        ids=self.save_annotation()
        self.conn.execute("UPDATE bank_questions SET stem=stem||' 且改变条件。' WHERE id=?",(ids[0],));self.conn.commit()
        self.assertIsNone(annotations.current(self.conn,self.data,ids[0]))
        self.assertIsNone(annotations.current(self.conn,self.data,ids[1]))

    def test_unrelated_catalogue_additions_and_alias_edits_do_not_invalidate_analysis(self):
        ids=self.save_annotation();value=catalog.base_document(self.conn)
        next(n for n in value['nodes'] if n['id']=='GS-04-001')['aliases'].append('复合导数法则')
        parent=catalog.active_id(self.conn)
        draft=catalog.create_draft(self.conn,value,expected_parent=parent)
        catalog.publish(self.conn,draft['id'],expected_parent=parent,reviewer='isolated-catalog-review')
        self.assertIsNotNone(annotations.current(self.conn,self.data,ids[0]))
        value=catalog.base_document(self.conn);node=next(n for n in value['nodes'] if n['id']=='GS-04-001')
        node['conditions'].append('数学条件发生改变，需要复核。')
        parent=catalog.active_id(self.conn);draft=catalog.create_draft(self.conn,value,expected_parent=parent)
        catalog.publish(self.conn,draft['id'],expected_parent=parent,reviewer='isolated-catalog-review')
        self.assertIsNone(annotations.current(self.conn,self.data,ids[0]))

    def test_missing_catalogue_is_saved_but_not_in_default_candidate_pool(self):
        self.prepare_catalog();ids=self.seed_questions()
        self.start('annotate_questions',{'bank_ids':ids});self.read_annotation_material()
        self.tool('apply_report',{'result':self.envelope(self.annotation_result('needs_catalog'))})
        finish_task(self.conn,self.task['id']);self.conn.commit()
        self.assertEqual(annotations.current(self.conn,self.data,ids[0])['analysis']['status'],'needs_catalog')
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=['GS-04-001'])['total'],0)

    def test_reserved_question_can_be_prepared_internally_without_exposure_but_not_recommended(self):
        self.prepare_catalog();ids=self.seed_questions()
        save_preferences(self.conn,{'study_type':1,'reserved':[{'math_type':1,'year':'2020'}]});self.conn.commit()
        self.start('annotate_questions',{'bank_ids':ids});self.read_annotation_material()
        self.tool('apply_report',{'result':self.envelope(self.annotation_result())})
        self.assertEqual(self.conn.execute('SELECT count(*) FROM bank_views').fetchone()[0],0)
        self.assertEqual(annotations.search(self.conn,self.data,topic_ids=['GS-04-001'])['total'],0)

    def test_scope_is_durable_and_visible_without_fake_paper_and_request_cannot_change_it(self):
        scope={'source_version_id':self.f.sid,'source_ids':['GS-04-001']};request=str(uuid.uuid4())
        job=enqueue(self.conn,self.root,self.data,'maintain_catalog',None,request,task_scope=scope)
        self.assertEqual(listing(self.conn)[0]['id'],job['id'])
        again=enqueue(self.conn,self.root,self.data,'maintain_catalog',None,str(uuid.uuid4()),task_scope=scope)
        self.assertEqual(again['id'],job['id'])
        with self.assertRaisesRegex(ValueError,'作用域'):
            enqueue(self.conn,self.root,self.data,'maintain_catalog',None,request,task_scope={**scope,'source_ids':['other']})
