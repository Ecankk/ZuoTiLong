from contextlib import closing
from copy import deepcopy
import json,sqlite3,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.bank import entities,source_records as r
from app.bank.question_identity import signature
from app.bank.identity_preview import preview
from app.bank.source_import import import_source
from app.storage.database import Database
import test_source_import as fixtures

PROOF=dict(stem=True,options=True,images=True,target=True,evidence='Synthetic complete source verification')


class QuestionEntityTests(unittest.TestCase):
    def setUp(self):
        self.f=fixtures.SourceImportTests();self.f.setUp();self.addCleanup(self.f.doCleanups)
        self.root=self.f.root

    def test_singletons_are_stable_and_do_not_rewrite_bank_or_annotations(self):
        self.f.batch=[fixtures.question('a'),fixtures.question('b')];self.f.save();self.f.apply()
        with closing(sqlite3.connect(self.f.config.library_database)) as conn:
            conn.row_factory=sqlite3.Row
            names=('bank_questions','bank_resources','bank_source_records','bank_source_versions','question_annotations','question_annotation_links')
            before={t:[tuple(x) for x in conn.execute('SELECT * FROM '+t)] for t in names}
        with patch('app.bank.annotations.materials',side_effect=AssertionError('No material reads at startup')),patch.object(Path,'read_bytes',side_effect=AssertionError('No asset hashing at startup')):
            Database(self.f.config).initialize()
        with closing(sqlite3.connect(self.f.config.library_database)) as conn:
            old=list(conn.execute('SELECT * FROM question_entity_members ORDER BY bank_id'))
            self.assertEqual(len(old),2);self.assertEqual(len({x[1] for x in old}),2)
            self.assertEqual([x[2] for x in old],[None,None])
            self.assertEqual({t:[tuple(x) for x in conn.execute('SELECT * FROM '+t)] for t in names},before)
        Database(self.f.config).initialize()
        with closing(sqlite3.connect(self.f.config.library_database)) as conn:
            self.assertEqual(list(conn.execute('SELECT * FROM question_entity_members ORDER BY bank_id')),old)
            self.assertEqual(conn.execute('SELECT count(*) FROM question_entity_events').fetchone()[0],2)
        with Database(self.f.config).session() as conn:
            with self.assertRaises(sqlite3.OperationalError):conn.execute("UPDATE question_entities SET revision=2")

    def test_signature_covers_options_figures_type_and_text_but_not_reference_or_source(self):
        a=fixtures.question();a['stem']=r.resource('Question\r\ne\u0301')
        x=signature(a,self.root,completeness=PROOF);self.assertTrue(x['automatic_eligible'])
        b=deepcopy(a);b['stem']=r.resource('Question\né');b['source_id']='S03';b['answer']=r.resource('B')
        self.assertEqual(signature(b,self.root,completeness=PROOF)['sha256'],x['sha256'])
        for field in ('question_type','options','stem'):
            b=deepcopy(a)
            if field=='question_type':b[field]='proof'
            elif field=='options':b[field][0]['content']=r.resource('different')
            else:b[field]=r.resource('Question 2')
            self.assertNotEqual(signature(b,self.root,completeness=PROOF)['sha256'],x['sha256'])
        from PIL import Image
        path=self.root/'diagram.png';Image.new('RGB',(2,2),'red').save(path)
        im=dict(path='diagram.png',sha256=r.sha256(path.read_bytes()),media_type='image/png')
        b=deepcopy(a);b['supplemental_figures']=dict(entries=[dict(figure_id='one',role='stem',image=im)],materialized_roles=[])
        self.assertNotEqual(signature(b,self.root,completeness=PROOF)['sha256'],x['sha256'])
        Image.new('RGB',(2,2),'blue').save(path)
        self.assertFalse(signature(b,self.root,completeness=PROOF)['automatic_eligible'])
        self.assertFalse(signature(a,self.root)['automatic_eligible'])
        b=deepcopy(a);b['options'][0]['content']=r.resource('![missing](asset://foo)')
        self.assertIn('unresolved_image_reference',signature(b,self.root,completeness=PROOF)['issues'])

    def test_singleton_upgrade_preserves_real_ready_annotation_and_material_hashes(self):
        import test_prepared_practice as prepared
        import database_fixture as server
        f=prepared.PreparedPracticeTests();f.setUp();self.addCleanup(f.tearDown)
        from app.bank.annotations import current,materials
        annotation=current(f.conn,f.data,prepared.BANK)
        self.assertEqual(annotation['analysis']['status'],'ready')
        before=dict(annotation);material=materials(f.conn,f.data,prepared.BANK)
        rows_before=list(f.conn.execute('SELECT * FROM question_annotation_links'))
        f.conn.commit();Database(server.config()).initialize()
        self.assertEqual(dict(current(f.conn,f.data,prepared.BANK)),before)
        self.assertEqual(materials(f.conn,f.data,prepared.BANK),material)
        self.assertEqual(list(f.conn.execute('SELECT * FROM question_annotation_links')),rows_before)

    def test_readonly_preview_groups_and_answers_conflict_without_writing_entities(self):
        self.f.batch=[fixtures.question('a'),fixtures.question('b')];self.f.save();self.f.apply()
        path=self.f.config.library_database;before=path.read_bytes()
        report=preview(self.f.config.library_dir)
        self.assertEqual(report['counts']['automatic_groups'],0);self.assertEqual(report['counts']['pending_groups'],1)
        self.assertIn('full_question_completeness_unproven_or_invalid',report['pending_review'][0]['reasons'])
        proofs={x['bank_id']:dict(PROOF,question_sha256=x['signature_sha256']) for x in report['signatures']}
        automatic=preview(self.f.config.library_dir,completeness=proofs)
        self.assertEqual(automatic['counts']['automatic_groups'],1)
        self.assertEqual(path.read_bytes(),before)
        self.assertNotIn('Invented fixture',json.dumps(automatic))
        self.assertEqual(automatic['counts']['singleton_members'],0)
        bid=r.bank_id(self.f.batch[1])
        with closing(sqlite3.connect(path)) as conn,conn:conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('B',bid))
        report=preview(self.f.config.library_dir,completeness=proofs)
        self.assertEqual(report['counts']['automatic_groups'],0)
        self.assertIn('answer_conflict_requires_review',report['pending_review'][0]['reasons'])
        proofs[bid]['question_sha256']='0'*64
        report=preview(self.f.config.library_dir,completeness=proofs)
        self.assertIn('coverage_signature_stale',next(x for x in report['signatures'] if x['bank_id']==bid)['issues'])

    def test_command_never_initializes_database_and_missing_library_not_created(self):
        self.f.apply();out=self.root/'report.json'
        script=Path(__file__).resolve().parents[1]/'scripts/preview_bank_identities.py'
        result=subprocess.run([sys.executable,'-X','utf8',str(script),'--library',str(self.f.config.library_dir),'--dry-run','--report',str(out)],capture_output=True,text=True,encoding='utf8')
        self.assertEqual(result.returncode,0,result.stderr);self.assertTrue(json.loads(out.read_text(encoding='utf8'))['read_only'])
        missing=self.root/'missing'
        with self.assertRaises(ValueError):preview(missing)
        self.assertFalse(missing.exists())

    def test_installed_legacy_windows_paths_are_read_without_source_path_relaxation(self):
        self.f.apply()
        from PIL import Image
        assets=self.f.config.library_dir/'bank-assets';assets.mkdir(exist_ok=True)
        Image.new('RGB',(2,2),'red').save(assets/'question.png')
        with closing(sqlite3.connect(self.f.config.library_database)) as conn,conn:
            conn.execute('DELETE FROM bank_source_records')
            conn.execute("UPDATE bank_resources SET question_path='bank-assets\\question.png'")
        report=preview(self.f.config.library_dir)
        self.assertNotIn('image_missing_or_unsafe',report['signatures'][0]['issues'])
        self.assertNotIn('image_missing_unsafe_or_hash_mismatch',report['signatures'][0]['issues'])

    def test_only_current_full_role_human_confirmation_can_bypass_coverage_declaration(self):
        import test_bank_identity_reviews as reviewed
        f=reviewed.BankIdentityReviewTests();f.setUp();self.addCleanup(f.doCleanups)
        f.service.review_identity(f.body())
        report=preview(f.config.library_dir)
        self.assertTrue(any(g['bank_ids']==f.ids[:2] and 'confirmed_review' in g['reasons'] for g in report['automatic']))
        f.conn.execute('UPDATE bank_questions SET answer=? WHERE id=?',('conflicting answer',f.ids[1]));f.conn.commit()
        report=preview(f.config.library_dir)
        self.assertFalse(any(g['bank_ids']==f.ids[:2] for g in report['automatic']))
        f.conn.execute('UPDATE bank_questions SET stem=? WHERE id=?',('changed question',f.ids[1]));f.conn.commit()
        report=preview(f.config.library_dir)
        self.assertFalse(any('confirmed_review' in g['reasons'] for g in report['automatic']))

    def test_incremental_exact_match_is_pending_across_collections_until_explicit_decision(self):
        self.f.apply(); Database(self.f.config).initialize()
        first=r.bank_id(self.f.batch[0])
        self.f.batch=[fixtures.question('second', source='S03')]; self.f.save()
        plan=import_source(self.f.config,'S03',self.f.path,collection='other')
        self.assertTrue(plan['identity_pending'])
        self.assertTrue(any(item.get('kind')=='identity' for item in plan['collection_conflicts']))
        import_source(self.f.config,'S03',self.f.path,collection='other',confirm=plan['plan_sha256'])
        second=r.bank_id(self.f.batch[0])
        with closing(sqlite3.connect(self.f.config.library_database)) as conn:
            conn.row_factory=sqlite3.Row
            before=conn.execute('SELECT * FROM question_entity_members WHERE bank_id=?',(second,)).fetchone()
            self.assertEqual(before['state'],'pending')
            self.assertEqual(before['entity_id'],conn.execute('SELECT entity_id FROM question_entity_members WHERE bank_id=?',(first,)).fetchone()[0])
        decisions=self.root/'identities.json';decisions.write_text(json.dumps({'schema':'mathlens.bank-identities/v1','entries':[{
            'source_uid':'second','bank_id':first,'decision':'same','entity_collection_id':'zhenti',
            'reason':'full question checked','evidence':'fixture evidence'}]},ensure_ascii=False),encoding='utf8')
        promoted=import_source(self.f.config,'S03',self.f.path,collection='other',identities=decisions)
        self.assertTrue(promoted['identity_matches'])
        import_source(self.f.config,'S03',self.f.path,collection='other',identities=decisions,confirm=promoted['plan_sha256'])
        with closing(sqlite3.connect(self.f.config.library_database)) as conn:
            self.assertEqual(conn.execute('SELECT state FROM question_entity_members WHERE bank_id=?',(second,)).fetchone()[0],'confirmed')
            from app.bank.entities import visible_ids,presentation
            self.assertEqual(visible_ids(conn,[first,second]),[first])
            self.assertEqual({item['bank_id'] for item in presentation(conn,first)['sources']},{first,second})
