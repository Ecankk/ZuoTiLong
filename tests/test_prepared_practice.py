from app.storage.boundaries import library_root
"""Prepared pool admission in a disposable study/bank fixture."""
import copy,json,unittest,uuid
from types import SimpleNamespace
from unittest.mock import patch
from PIL import Image
import database_fixture as server
import test_mapping_versions as mapping_fixtures
import test_question_annotations as annotation_fixtures
from app.bank import annotations
from app.bank.access import init_access
from app.learning.tasks import create_task,bind_turn,deliver,finish_task,receipt
from app.learning.loop import apply_report
from app.learning.practice_knowledge import material_binding

TOPIC='GS-04-001'
BANK='math2-2020-01'


class PreparedPracticeTests(unittest.TestCase):
    def setUp(self):
        self.m=mapping_fixtures.MappingVersionsTests();self.m.setUp()
        self.f=self.m.f;self.conn=self.f.conn;self.data=self.f.data
        report=copy.deepcopy(self.f.fixture.report)
        for q in report['questions']:
            q.update(stem='求 f(x)=sin(x²) 的导数。',knowledge=['复合函数求导'],
                reference_answer='2x cos(x²)',reference_reasoning='先求外层sin的导数，再乘内层平方的导数。',
                fingerprint={'conditions':['f(x)=sin(x²)'],'goal':'求导','methods':['链式法则'],'operations':['逐层求导']})
        apply_report(self.conn,'paper-test',report,self.f.root)
        assets=library_root(self.data)/'bank-assets';assets.mkdir(exist_ok=True)
        for role,color in [('question','white'),('analysis','lightblue')]:Image.new('RGB',(40,40),color).save(assets/(role+'.png'))
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at) VALUES(?,?,?,?,?,'now')",
            (BANK,'isolated-prepared','求 f(x)=sin(x²) 的导数。','2x cos(x²)','外层求导乘内层导数。'))
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',
            (BANK,'{}','bank-assets/question.png','bank-assets/analysis.png',None))
        init_access(self.conn);self.conn.commit()
        task=create_task(self.conn,self.f.root,self.data,'annotate_questions',None,'prepared-session',str(uuid.uuid4()),task_scope={'bank_ids':[BANK]})
        lease=self.bind(task,'prepared-session')
        self.tool('read_bank',{'bank_id':BANK,'role':'all'},lease)
        self.tool('task_context',{'topic_ids':[TOPIC]},lease)
        result=annotation_fixtures.QuestionPreparationTests.annotation_result(SimpleNamespace(task=task))
        payload={'schema_version':'1.7','task_id':task['id'],'kind':task['kind'],'paper_id':None,
                 'input_revision':task['input_revision'],'author':'isolated-annotation','result':result}
        deliver(self.conn,self.f.root,self.data,payload,lease);finish_task(self.conn,task['id']);self.conn.commit()
        self.annotation=annotations.current(self.conn,self.data,BANK)

    def tearDown(self):self.m.tearDown()

    def bind(self,task,session):
        bind_turn(self.conn,task['id'],session,task['run_token'],'turn-test');self.conn.commit()
        return {'task_id':task['id'],'session_id':session,'run_token':task['run_token'],'turn_id':'turn-test'}

    def tool(self,action,payload,lease=None):
        from app.agent.tools import execute
        self.conn.commit()
        with patch('app.agent.tools.connection',lambda data:server.connect()):
            content=execute(self.f.root,self.data,action,payload,lease=lease or self.f.lease)
        return json.loads(content[0]['text'])

    def start(self,version='1.8'):
        self.m.save(version=version)
        self.f.start('prepare_practice',contract_version='1.9')

    def read(self,recall=True):
        self.tool('task_context',{'topic_ids':[TOPIC]})
        if recall:
            result=self.tool('catalog',{'topic_ids':[TOPIC]})
            self.assertEqual([q['id'] for q in result['items']],[BANK])
        question=self.tool('read_bank',{'bank_id':BANK,'role':'all'})
        self.assertIn('reference_reasoning',question['prepared_question'])
        self.assertEqual(question['prepared_question']['material_binding']['annotation_id'],self.annotation['id'])

    def payload(self):
        return self.f.envelope({'goals':[{'id':'chain','label':'复合函数链式求导','question_numbers':[1,2],
            'topic_ids':[TOPIC],'stage':'formula','evidence':'两题漏乘内层导数。','priority':1,
            'decision':'practice','reason':'一题检验两处相同操作。','related_probe_ids':[]}],
            'exercises':[{'id':'one','goal_ids':['chain'],'bank_id':BANK,
                'annotation_id':self.annotation['id'],'prompt':'指出内外层函数并求导。',
                'expected':'2x cos(x²)','solution_note':'按链式法则逐层求导。',
                'selection_reason':'检验是否保留内层导数。','repeat_reason':None}],
            'retained_exercises':[],'limitations':[]})

    def test_original_mapping_is_required_before_prepared_selection(self):
        with self.assertRaisesRegex(ValueError,'映射尚未就绪'):
            self.f.start('prepare_practice',contract_version='1.9')

    def test_legacy_unversioned_mapping_is_not_silently_accepted(self):
        with self.assertRaisesRegex(ValueError,'映射尚未就绪'):self.start(version='1.6')

    def test_ready_recall_definition_and_materials_save_one_shared_binding(self):
        self.start();self.read();before=self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0]
        saved=deliver(self.conn,self.f.root,self.data,self.payload(),self.f.lease)
        row=self.conn.execute('SELECT * FROM practice_question_bindings WHERE result_id=?',(saved['result_id'],)).fetchone()
        self.assertIsNotNone(row);self.assertEqual(row['bank_id'],BANK)
        self.assertEqual(row['content_revision'],self.annotation['content_revision'])
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_attempts').fetchone()[0],before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM probe_goals WHERE probe_id=?',(row['probe_id'],)).fetchone()[0],1)

    def test_reading_raw_bank_without_prepared_recall_cannot_bypass_admission(self):
        self.start();self.read(recall=False)
        before=self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0]
        with self.assertRaisesRegex(ValueError,'prepared_recall'):
            deliver(self.conn,self.f.root,self.data,self.payload(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM diagnostic_probes').fetchone()[0],before)
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_question_bindings').fetchone()[0],0)

    def test_unknown_goal_id_rolls_back_all_plan_changes(self):
        self.start();self.read();payload=self.payload();payload['result']['goals'][0]['topic_ids']=['made-up-concept']
        with self.assertRaisesRegex(ValueError,'目录外'):
            deliver(self.conn,self.f.root,self.data,payload,self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))
        self.assertEqual(self.conn.execute('SELECT count(*) FROM practice_question_bindings').fetchone()[0],0)

    def test_new_material_after_read_is_rejected_without_creating_an_attempt(self):
        self.start();self.read()
        Image.new('RGB',(40,40),'red').save(library_root(self.data)/'bank-assets/analysis.png')
        with self.assertRaisesRegex(ValueError,'读取|ready|标注'):
            deliver(self.conn,self.f.root,self.data,self.payload(),self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def test_annotation_id_must_be_the_captured_version(self):
        self.start();self.read();payload=self.payload();payload['result']['exercises'][0]['annotation_id']='annotation-foreign'
        with self.assertRaisesRegex(ValueError,'ready|标注'):
            deliver(self.conn,self.f.root,self.data,payload,self.f.lease)
        self.assertIsNone(receipt(self.conn,self.f.task['id']))

    def test_alias_binding_records_actual_reference_materials_independently(self):
        alias='math3-2020-01'
        self.conn.execute("INSERT INTO bank_questions(id,source,stem,answer,explanation,created_at) VALUES(?,?,?,?,?,'now')",
            (alias,'isolated-alias','求 f(x)=sin(x²) 的导数。','2x cos(x²)','另一个等价的解析表述。'))
        self.conn.execute('INSERT INTO bank_resources VALUES(?,?,?,?,?)',(alias,'{}','bank-assets/question.png',None,None))
        init_access(self.conn);self.conn.execute('INSERT INTO bank_links VALUES(?,?,?)',(BANK,alias,'confirmed same mathematical question'))
        # The math annotation stays common; the selected alias's materials are
        # not asserted to have the canonical reference's hash or review.
        binding=material_binding(self.conn,self.data,alias,self.annotation)
        self.assertEqual(binding['content_revision'],self.annotation['content_revision'])
        self.assertNotEqual(binding['material_revision'],binding['annotation_material_revision'])
