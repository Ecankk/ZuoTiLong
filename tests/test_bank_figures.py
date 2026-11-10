import copy,json,unittest
from pathlib import Path
from PIL import Image
import test_source_import as fixtures
from app.bank import source_records as r,source_import as imp
from app.storage.database import Database

class FigureTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SourceImportTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.f.apply();self.bid=r.bank_id(self.f.batch[0]);self.path=self.f.root/'figures.json'
        image=self.f.root/'draw.png';Image.new('RGB',(21,19),'white').save(image)
        self.doc=dict(schema='mathlens.bank-figures/v1',source_id='S02',revision=self.f.batch[0]['revision'],collection_id='zhenti',entries=[dict(figure_id='diagram-1',match={'source_uid':'one'},role='stem',image=dict(path='draw.png',sha256=r.sha256(image.read_bytes()),media_type='image/png'),kind='redrawn',caption='按题意重绘',reason='缺图',evidence='隔离题意')])
        self.write()
    def write(self):self.path.write_text(r.canonical(self.doc),encoding='utf8')
    def run_import(self,**kw):return self.f.run_import(figures=self.path,**kw)
    def test_preview_confirm_history_materials_and_idempotence(self):
        with imp.library(self.f.config) as c:old=[tuple(x) for x in c.execute('select * from bank_source_versions')]
        assets=list(self.f.config.library_dir.rglob('*.png'));plan=self.run_import()
        self.assertEqual(assets,list(self.f.config.library_dir.rglob('*.png')));self.assertEqual(plan['updated'],[self.bid])
        self.assertEqual(plan['figures_applied'][0]['action'],'added');self.assertIsNotNone(plan['figures_applied'][0]['new_material_revision'])
        self.run_import(confirm=plan['plan_sha256'])
        with imp.library(self.f.config) as c:
            saved=json.loads(c.execute('select record_json from bank_source_records').fetchone()[0]);self.assertEqual(saved['original'],self.f.batch[0]['original']);self.assertEqual(saved['stem'],self.f.batch[0]['stem'])
            self.assertTrue(set(old).issubset({tuple(x) for x in c.execute('select * from bank_source_versions')}))
            meta=json.loads(c.execute('select metadata_json from bank_resources').fetchone()[0]);self.assertEqual(meta['supplemental_figures']['entries'][0]['kind'],'redrawn')
        self.assertEqual(self.run_import()['unchanged'],[self.bid])
        with self.assertRaisesRegex(ValueError,'incomplete'):self.f.run_import()
        self.doc['entries'][0]['reason']='补充核对说明';self.write();plan=self.run_import();self.assertEqual(plan['needs_annotation'],[]);self.run_import(confirm=plan['plan_sha256'])
        self.assertEqual(self.run_import()['unchanged'],[self.bid])
    def test_errors_and_stale_confirmation(self):
        plan=self.run_import();Image.new('RGB',(22,20),'black').save(self.f.root/'draw.png')
        with self.assertRaisesRegex(ValueError,'hash_mismatch'):self.run_import(confirm=plan['plan_sha256'])
        self.doc['entries'][0]['image']['sha256']=r.sha256((self.f.root/'draw.png').read_bytes());self.write()
        with self.assertRaisesRegex(ValueError,'Preview changed'):self.run_import(confirm=plan['plan_sha256'])
        for key,value in [('kind','source_scan'),('role','answer'),('evidence','')]:
            before=copy.deepcopy(self.doc);self.doc['entries'][0][key]=value;self.write()
            with self.assertRaises(Exception):self.run_import()
            self.doc=before
        self.doc['entries'][0]['image']['path']='../outside.png';self.write()
        with self.assertRaises(ValueError):self.run_import()
    def test_collection_pack_preserves_figure_and_does_not_double_compose(self):
        plan=self.run_import();self.run_import(confirm=plan['plan_sha256'])
        Database(self.f.config).initialize()
        from app.bank import collection_packs as packs
        from app.config import AppConfig
        archive=self.f.root/'pack.zip';packs.export_collection(self.f.config,'zhenti',archive)
        target=AppConfig(self.f.root,self.f.root/'target-workspace',self.f.root/'dist',self.f.root/'target-workspace'/'learning.db',library=self.f.root/'target-library')
        Database(target).initialize()
        plan=packs.import_collection(target,archive);packs.import_collection(target,archive,plan['plan_sha256'])
        with imp.library(target) as c:
            p=c.execute('select question_path from bank_resources').fetchone()[0]
            with Image.open(target.library_dir/p) as image:self.assertEqual(image.size,(21,19))
        self.assertEqual(packs.import_collection(target,archive)['unchanged'],[self.bid])

    def test_changed_picture_invalidates_ready_annotation_and_new_read_has_figure(self):
        import test_prepared_practice as prepared
        import database_fixture as server
        from app.bank import annotations,figures
        f=prepared.PreparedPracticeTests();f.setUp();self.addCleanup(f.tearDown)
        c=f.conn;bid=prepared.BANK;before=annotations.current(c,f.data,bid);self.assertEqual(before['analysis']['status'],'ready')
        from app.learning.practice_knowledge import material_binding
        from app.storage.practice_materials import freeze,load
        frozen=freeze(c,f.data,material_binding(c,f.data,bid,before))
        from app.storage.boundaries import library_root
        lib=library_root(f.data);materials=annotations.materials(c,f.data,bid);q=fixtures.question();q['options']=[]
        c.execute("INSERT INTO bank_collections VALUES('figure-test','Synthetic figures','other',99)")
        c.execute("UPDATE bank_questions SET collection_id='figure-test' WHERE id=?",(bid,))
        for role,key in [('question','stem'),('answer','answer'),('analysis','analysis')]:
            item=materials.get(role,{})
            images=[dict(path=item['path'],sha256=item['image_sha256'],media_type='image/png')] if item.get('path') else []
            q[key]=r.resource(item.get('text',''),images)
        c.execute('INSERT INTO bank_source_records VALUES(?,?,?,?,?,?,?)',(bid,q['source_id'],q['source_uid'],q['revision'],r.digest([q,[]]),r.canonical(q),'[]'));c.commit()
        doc=copy.deepcopy(self.doc);doc['collection_id']=c.execute('select collection_id from bank_questions where id=?',(bid,)).fetchone()[0]
        path=f.data/'figures.json';Image.new('RGB',(15,17),'blue').save(f.data/'draw.png');doc['entries'][0]['image']['sha256']=r.sha256((f.data/'draw.png').read_bytes());path.write_text(r.canonical(doc),encoding='utf8')
        batch=[q];audit=figures.apply(batch,path,f.data,doc['collection_id']);ids={(q['source_id'],q['source_uid']):bid}
        plan=imp.preview(c,batch,{'figures':audit},[],[],doc['collection_id'],bank_ids=ids,asset_root=lib,figure_root=f.data)
        self.assertIn(bid,plan['invalidated_annotations']);self.assertTrue(plan['figures_applied'][0]['annotation_invalidated'])
        imp._apply(c,server.config(),batch,plan,lib,bank_ids=ids,figure_root=f.data,initialize_schema=False);c.commit()
        self.assertIsNone(annotations.current(c,f.data,bid))
        self.assertTrue(c.execute('select 1 from question_annotations where id=?',(before['id'],)).fetchone())
        task=prepared.create_task(c,f.f.root,f.data,'annotate_questions',None,'figure-session',__import__('uuid').uuid4().hex,task_scope={'bank_ids':[bid]})
        lease=f.bind(task,'figure-session');result=f.tool('read_bank',{'bank_id':bid,'role':'all'},lease)
        self.assertEqual(result['supplemental_figures'][0]['caption'],'按题意重绘')
        self.assertEqual(load(f.data,frozen['snapshot_key'],frozen['snapshot_sha256']),frozen['material_manifest'])
        f.tool('task_context',{'topic_ids':[prepared.TOPIC]},lease)
        import test_question_annotations as af
        from types import SimpleNamespace
        payload=dict(schema_version='1.7',task_id=task['id'],kind='annotate_questions',paper_id=None,input_revision=task['input_revision'],author='fake',result=af.QuestionPreparationTests.annotation_result(SimpleNamespace(task=task)))
        prepared.deliver(c,f.f.root,f.data,payload,lease);c.commit()
        self.assertEqual(annotations.current(c,f.data,bid)['analysis']['status'],'ready')
        from app.bank import collection_packs as packs
        from app.config import AppConfig
        archive=f.data/'figures-pack.zip';packs.export_collection(server.config(),doc['collection_id'],archive)
        target=AppConfig(f.f.root,f.data/'target',f.data/'dist',f.data/'target'/'learning.db',library=f.data/'target-library')
        Database(target).initialize()
        p=packs.import_collection(target,archive);packs.import_collection(target,archive,p['plan_sha256'])
        with packs.connection(target) as conn:self.assertEqual(annotations.current(conn,target.data,bid)['analysis']['status'],'ready')
        again=packs.import_collection(target,archive);self.assertIn(bid,again['unchanged']);self.assertEqual(again['updated'],[])
