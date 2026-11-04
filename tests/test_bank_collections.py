"""Collections are partitions, not mathematical/source identities."""
import copy,json,sqlite3,unittest
from unittest.mock import patch
from app.bank import collections,annotation_packages
from app.bank.source_import import import_source
from app.bank import source_records

class CollectionImportTests(unittest.TestCase):
    def setUp(self):
        from test_source_import import SourceImportTests
        self.f=SourceImportTests();self.f.setUp();self.addCleanup(self.f.doCleanups)

    def test_collection_is_required_hashed_and_cannot_move_existing_question(self):
        f=self.f
        with self.assertRaises(TypeError):import_source(f.config,'S02',f.path)
        first=import_source(f.config,'S02',f.path,collection='zhenti')
        other=import_source(f.config,'S02',f.path,collection='other')
        self.assertNotEqual(first['plan_sha256'],other['plan_sha256'])
        import_source(f.config,'S02',f.path,collection='zhenti',confirm=first['plan_sha256'])
        conflict=import_source(f.config,'S02',f.path,collection='other')
        self.assertEqual(conflict['collection_conflicts'][0]['existing'],'zhenti')
        with self.assertRaisesRegex(ValueError,'Collection conflict'):
            import_source(f.config,'S02',f.path,collection='other',confirm=conflict['plan_sha256'])
        repeat=import_source(f.config,'S02',f.path,collection='zhenti')
        self.assertEqual(len(repeat['unchanged']),1)

    def test_book_metadata_is_additive_and_never_implies_exam_identity(self):
        f=self.f;record=f.batch[0]
        record.update(exam_year=None,math_type=None,number=None,book=dict(title='Invented workbook',edition=None,
            part='Strengthening',chapter='Derivatives',number=None,locator='chapter-32#q1'))
        f.save();plan=import_source(f.config,'S02',f.path,collection='zhangyu-1000')
        import_source(f.config,'S02',f.path,collection='zhangyu-1000',confirm=plan['plan_sha256'])
        with sqlite3.connect(f.config.library_database) as conn:
            metadata=json.loads(conn.execute('SELECT metadata_json FROM bank_resources').fetchone()[0])
            self.assertEqual(metadata['book'],record['book'])
            self.assertEqual(conn.execute('SELECT math_type,year,number FROM bank_identity').fetchone(),(0,'',0))

class CollectionNavigationTests(unittest.TestCase):
    def setUp(self):
        from test_knowledge_links import KnowledgeLinksTests
        from app.runtime import AppRuntime
        self.f=KnowledgeLinksTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.conn=self.f.conn;self.rt=AppRuntime(self.f.config,agent_factory=None);self.addCleanup(self.rt.close)

    def test_migration_changes_only_membership_not_ids_materials_or_annotations(self):
        from app.bank.annotations import current,materials
        from app.knowledge import catalog
        ids=self.f.ids
        self.conn.execute('UPDATE bank_questions SET source=? WHERE id=?',(collections.LEGACY[0],ids[0]))
        self.conn.execute("UPDATE bank_questions SET source='本地示例题库' WHERE id=?",(ids[1],));self.conn.commit()
        before=[(bid,materials(self.conn,self.f.f.data,bid),current(self.conn,self.f.f.data,bid)) for bid in ids]
        raw=[tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')]
        self.conn.execute('DROP INDEX library.idx_bank_collection')
        self.conn.execute('DROP TRIGGER library.bank_collection_delete')
        self.conn.execute('DROP TRIGGER library.bank_collection_rename')
        for trigger in list(self.conn.execute("SELECT name FROM library.sqlite_master WHERE type='trigger' AND tbl_name='bank_questions'")):
            self.conn.execute('DROP TRIGGER library.'+trigger[0])
        self.conn.execute('ALTER TABLE library.bank_questions DROP COLUMN collection_id')
        self.conn.commit()
        with sqlite3.connect(self.f.config.library_database) as legacy:collections.initialize(legacy)
        self.assertEqual([collections.membership(self.conn,b) for b in ids],['zhenti','example'])
        self.assertEqual(raw,[tuple(r) for r in self.conn.execute('SELECT * FROM question_annotations')])
        self.assertEqual(before,[(bid,materials(self.conn,self.f.f.data,bid),current(self.conn,self.f.f.data,bid)) for bid in ids])
        with sqlite3.connect(self.f.config.library_database) as legacy:collections.initialize(legacy)
        self.assertEqual([collections.membership(self.conn,b) for b in ids],['zhenti','example'])

    def test_collection_http_filter_counts_and_navigation_cards(self):
        from fastapi.testclient import TestClient
        from app.main import create_app
        self.conn.execute('UPDATE bank_questions SET collection_id=? WHERE id=?',('zhangyu-1000',self.f.ids[0]));self.conn.commit()
        with TestClient(create_app(self.f.config,agent_factory=None),base_url='http://127.0.0.1') as client:
            result=client.get('/api/bank/collections');self.assertEqual(result.status_code,200,result.text)
            groups={v['id']:v for v in result.json()};self.assertEqual(groups['zhangyu-1000']['total'],1);self.assertEqual(groups['zhangyu-1000']['ready'],1)
            bank=client.get('/api/bank?collection=zhangyu-1000&limit=1').json()
            self.assertEqual(bank['total'],1);self.assertEqual(bank['items'][0]['collection_id'],'zhangyu-1000')
            search=client.get('/api/bank/search?topic_id=GS-04-001&collection=zhangyu-1000').json()
            self.assertEqual(search['total'],1);self.assertEqual(search['items'][0]['collection_id'],'zhangyu-1000')
            card=client.get('/api/knowledge/links?topic_id=GS-04-001&collection=zhangyu-1000').json()['items'][0]['sources']
            self.assertEqual([v['collection_id'] for v in card],['zhangyu-1000'])
            detail=client.get('/api/knowledge/topics/GS-04-001').json()
            self.assertEqual({v['collection_id'] for v in detail['collection_counts']},{'other','zhangyu-1000'})
            self.assertEqual(client.get('/api/bank?collection=unknown').status_code,400)

    def test_index_package_collection_is_hashed_and_never_matches_another_partition(self):
        bid=self.f.ids[0]
        self.conn.execute("UPDATE bank_questions SET collection_id='zhenti'");self.conn.commit()
        value=annotation_packages.export_package(self.conn,self.f.f.data,collection='zhenti')
        self.assertEqual(value['schema_version'],'mathlens.question-index/v2')
        self.assertTrue(all(e['collection_id']=='zhenti' for e in value['entries']))
        self.conn.execute('DELETE FROM question_annotation_links');self.conn.execute("UPDATE bank_questions SET collection_id='zhangyu-1000'");self.conn.commit()
        self.assertEqual(annotation_packages.preview(self.conn,self.f.f.data,value)['matched_local_records'],0)
        for entry in value['entries']:
            entry['collection_id']='zhangyu-1000';entry['sha256']=annotation_packages._sha(entry)
        value['sha256']=annotation_packages._sha(value)
        self.assertEqual(annotation_packages.preview(self.conn,self.f.f.data,value,collection='zhangyu-1000')['matched_local_records'],2)

class S03AdapterTests(unittest.TestCase):
    def test_type_mapping_no_invented_answer_and_book_locator(self):
        from scripts.bank_source_adapters.zhangyu_html import convert,adapt,REVISION
        item={'source':dict(source_file='chapters/chapter-32.html',source_uid='chapters/chapter-32.html#q1',source_question_number=1,source_file_sha256='a'*64),
            'identity':dict(book_title_claimed='Invented book',edition_label_claimed=None,part='强化篇',chapter_title='Example',subject='高等数学'),
            'content':dict(stem='Synthetic $x+1$',answer=None,explanation='Synthetic reasoning, not an answer parser.',options=[],illustrations=[]),
            'upstream':dict(question_type='解答')}
        for upstream,kind in [('选择','choice'),('填空','fill'),('解答','proof')]:
            item['upstream']['question_type']=upstream;record=convert(item)
            source_records.validate(record,'.')
            self.assertEqual(record['question_type'],kind);self.assertEqual(record['answer']['text'],'')
            self.assertEqual(record['revision'],REVISION);self.assertIsNone(record['book']['number'])
            self.assertIsNone(record['exam_year']);self.assertEqual(record['book']['part'],'强化篇')
        with self.assertRaisesRegex(ValueError,'not exam identities'):adapt('.',year=2026)
        with self.assertRaises(FileNotFoundError):adapt('nonexistent-source')

