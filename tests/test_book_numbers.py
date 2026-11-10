"""Chapter-local numbers enrich metadata without disturbing curated materials."""
import copy,json,unittest
from app.bank import source_records as records
from app.bank.book_numbers import initialize,REVISION
from app.bank.source_import import import_source
import test_source_import as source_fixtures


def book_record():
    q=source_fixtures.question('chapters/chapter-32.html#q5','S03',None)
    q.update(revision=REVISION,exam_year=None,math_type=None,math_types=[1],
        locator=dict(path='chapters/chapter-32.html',pointer='#q5',source_sha256='1'*64),
        book=dict(title='Synthetic book',edition=None,part='强化篇',chapter='Synthetic chapter',number=None,locator='chapters/chapter-32.html#q5'))
    return q


class BookNumbersTests(unittest.TestCase):
    def test_upgrade_preserves_ready_annotation_materials_fingerprint_and_errata(self):
        import test_prepared_practice as prepared
        from app.bank import annotations
        f=prepared.PreparedPracticeTests();f.setUp();self.addCleanup(f.tearDown)
        conn=f.conn;bid=prepared.BANK;q=book_record()
        erratum=dict(match={'source_uid':q['source_uid']},role='analysis',find='before',replace='after',reason='saved correction',evidence='fixture')
        q['errata']=[erratum]
        metadata=json.loads(conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()[0]);metadata.update(book=q['book'],errata=[erratum])
        conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(records.canonical(metadata),bid))
        conn.execute('INSERT INTO bank_source_records VALUES(?,?,?,?,?,?,?)',(bid,'S03',q['source_uid'],REVISION,records.digest([q,[]]),records.canonical(q),'[]'))
        conn.execute('INSERT INTO bank_source_versions VALUES(?,?,?,?,?)',(bid,records.digest([q,[]]),records.canonical(q),'[]','now'));conn.commit()
        actual=annotations.current(conn,f.data,bid);self.assertEqual(actual['analysis']['status'],'ready')
        material=annotations.materials(conn,f.data,bid)
        protected={t:[tuple(r) for r in conn.execute('SELECT * FROM '+t)] for t in ('bank_questions','bank_identity','question_annotations','question_annotation_links','annotation_provenance')}
        self.assertEqual(initialize(conn),[bid]);conn.commit()
        self.assertEqual(annotations.materials(conn,f.data,bid),material)
        self.assertEqual(annotations.current(conn,f.data,bid),actual)
        self.assertEqual(protected,{t:[tuple(r) for r in conn.execute('SELECT * FROM '+t)] for t in protected})
        updated=json.loads(conn.execute('SELECT record_json FROM bank_source_records WHERE bank_id=?',(bid,)).fetchone()[0])
        expected=copy.deepcopy(q);expected['book']['number']='5'
        self.assertEqual(updated,expected)
        self.assertEqual(conn.execute('SELECT count(*) FROM bank_source_versions WHERE bank_id=?',(bid,)).fetchone()[0],2)
        self.assertEqual(initialize(conn),[])

    def test_metadata_import_preserves_curated_rows_and_repeat_with_same_errata_is_unchanged(self):
        f=source_fixtures.SourceImportTests();f.setUp();self.addCleanup(f.doCleanups)
        f.batch=[book_record()];f.save();q=f.batch[0];bid=records.bank_id(q)
        path=f.root/'errata.json';path.write_text(records.canonical(dict(schema='mathlens.bank-errata/v1',source_id='S03',revision=REVISION,
            entries=[dict(match={'source_uid':q['source_uid']},role='analysis',find='1+1',replace='2+0',reason='fixture',evidence='fixture arithmetic')])),encoding='utf8')
        def run(**kwargs):return import_source(f.config,'S03',f.path,collection='zhangyu-1000',errata=path,**kwargs)
        run(confirm=run()['plan_sha256'])
        from app.bank.source_import import library
        with library(f.config,write=True) as conn:
            conn.execute("UPDATE bank_questions SET fingerprint_json='curated' WHERE id=?",(bid,));conn.execute("UPDATE bank_identity SET sha256=? WHERE bank_id=?",('a'*64,bid));conn.commit()
            before=[tuple(r) for r in conn.execute('SELECT * FROM bank_questions')];identity=[tuple(r) for r in conn.execute('SELECT * FROM bank_identity')]
        q['book']['number']='5';f.save();plan=run()
        self.assertEqual(plan['metadata_only'],[bid]);self.assertEqual(plan['invalidated_annotations'],[]);self.assertEqual(plan['needs_annotation'],[])
        run(confirm=plan['plan_sha256'])
        with library(f.config) as conn:
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM bank_questions')],before)
            self.assertEqual([tuple(r) for r in conn.execute('SELECT * FROM bank_identity')],identity)
            self.assertIn('2+0',conn.execute('SELECT explanation FROM bank_questions').fetchone()[0])
            self.assertEqual(json.loads(conn.execute('SELECT metadata_json FROM bank_resources').fetchone()[0])['book']['number'],'5')
        self.assertEqual(run()['unchanged'],[bid])
        # Omitting a correction must still reveal a real material change.
        raw=import_source(f.config,'S03',f.path,collection='zhangyu-1000')
        self.assertEqual(raw['updated'],[bid]);self.assertEqual(raw['metadata_only'],[])

    def test_only_pinned_consistent_strengthening_locators_are_enriched(self):
        from app.bank.book_numbers import number
        q=book_record();self.assertEqual(number(q),'5')
        for mutate in (lambda r:r.update(revision='other'),lambda r:r['locator'].update(pointer='#q6'),lambda r:r['book'].update(part='基础篇'),lambda r:r.update(source_uid='unknown')):
            value=copy.deepcopy(q);mutate(value);self.assertIsNone(number(value))
