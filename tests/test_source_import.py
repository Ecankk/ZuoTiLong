"""Import boundary tests use invented questions and private temporary libraries."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from jsonschema import ValidationError

from app.bank import source_records as records
from app.bank.source_import import import_source
from app.config import AppConfig
from app.storage.database import Database
from scripts.bank_source_adapters.cxy_daguan import convert


def question(uid='one', source='S02', number=1):
    original = dict(id=uid, stem='Invented fixture $x+1$')
    return dict(schema=records.SCHEMA, source_id=source, revision='fixture-revision-1', source_uid=uid,
        locator=dict(path='fixture.json', pointer='/0', source_sha256=records.digest([original])),
        exam_year=2026, math_type=1, number=number, question_type='choice', max_score=5,
        stem=records.resource(original['stem']), answer=records.resource('A'), analysis=records.resource('$1+1=2$'),
        options=[dict(label='A', content=records.resource('$2$')), dict(label='B', content=records.resource('$3$'))],
        original=dict(source_text='Invented source', record=original, sha256=records.digest(original)), tags=['fixture'])


class SourceImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = AppConfig(self.root, self.root/'workspace', self.root/'dist',
                                self.root/'workspace'/'learning.db', library=self.root/'library')
        self.path = self.root/'records.jsonl'
        self.batch = [question()]
        self.save()

    def save(self):
        self.path.write_text('\n'.join(records.canonical(r) for r in self.batch), encoding='utf8')

    def run_import(self, **kwargs):
        return import_source(self.config, 'S02', self.path, collection='zhenti', **kwargs)

    def apply(self, **kwargs):
        return self.run_import(confirm=self.run_import(**kwargs)['plan_sha256'], **kwargs)

    def test_preview_does_not_initialize_any_data_and_confirmation_is_required(self):
        plan = self.run_import()
        self.assertEqual(plan['added'], [records.bank_id(self.batch[0])])
        self.assertFalse(plan['applied'])
        self.assertFalse(self.config.data.exists())
        self.assertFalse(self.config.library_dir.exists())
        with self.assertRaisesRegex(ValueError, 'Preview changed'):
            self.run_import(confirm='wrong')
        self.assertFalse(self.config.library_dir.exists())
        self.apply()
        self.assertFalse(self.config.data.exists())

    def test_hash_schema_path_and_source_errors_reject_whole_batch(self):
        mutations = [lambda r: r['stem'].update(text='tampered'),
                     lambda r: r.update(question_type='objective'),
                     lambda r: r['original'].update(sha256='0'*64),
                     lambda r: r.update(source_id='S03'),
                     lambda r: r['stem']['images'].append(dict(path='../escape.png', sha256='0'*64, media_type='image/png')),
                     lambda r: r.update(max_score=float('inf'))]
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.batch = [question(), question('two', number=2)]
                mutate(self.batch[1])
                # allow_nan only in fixture output to exercise external JSON rejection.
                self.path.write_text('\n'.join(json.dumps(r) for r in self.batch), encoding='utf8')
                with self.assertRaises((ValueError, ValidationError)):
                    self.run_import()
                self.assertFalse(self.config.library_dir.exists())
        for path in ('C:/outside.png', '/outside.png', 'nested/../../outside.png', 'nested\\outside.png'):
            with self.assertRaises(ValueError):records.asset_path(self.root, path)

    def test_metadata_overrides_audit_exclusions_and_fail_on_conflict_or_mismatch(self):
        self.batch.append(question('unknown', number=None)); self.save()
        entry = dict(match={'source_uid':'one'}, set={'max_score':10}, reason='fixture print', evidence='page 1')
        overrides = dict(schema=records.OVERRIDES_SCHEMA, source_id='S02', revision='fixture-revision-1',
                         entries=[entry, dict(match={'source_uid':'unknown'}, set={'exclude':True}, reason='pending', evidence='no number')])
        path = self.root/'overrides.json'
        def save():path.write_text(json.dumps(overrides), encoding='utf8')
        save(); plan = self.run_import(overrides=path)
        self.assertEqual(len(plan['added']), 1)
        self.assertEqual(plan['excluded'][0]['source_uid'], 'unknown')
        self.assertEqual(plan['overrides_applied'][0]['old'], 5)
        self.assertEqual(plan['overrides_applied'][0]['new'], 10)
        self.apply(overrides=path)
        overrides['entries'].append(dict(entry, set={'max_score':12})); save()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):self.run_import(overrides=path)
        overrides['entries'] = [dict(entry, match={'source_uid':'not-in-batch'})]; save()
        with self.assertRaisesRegex(ValueError, 'Unmatched'):self.run_import(overrides=path)
        overrides['entries'] = [dict(entry, set={'stem':'not metadata'})]; save()
        with self.assertRaises(ValidationError):self.run_import(overrides=path)
        overrides['entries'] = [dict(entry, set={'number':2}), dict(entry,
            match={'exam_year':2026,'math_type':1,'number':1}, set={'number':3})];save()
        with self.assertRaisesRegex(ValueError, 'Conflicting'):self.run_import(overrides=path)

    def test_idempotence_preserves_rows_assets_fingerprint_notes_and_exposure(self):
        from PIL import Image
        image = self.root/'question.png'; Image.new('RGB', (20, 20), 'white').save(image)
        self.batch[0]['stem'] = records.resource('', [dict(path=image.name, sha256=records.sha256(image.read_bytes()), media_type='image/png')])
        self.save(); self.apply()
        Database(self.config).initialize()
        from app.bank.access import reveal
        with Database(self.config).session(write=True, library_write=True) as conn:
            bid = records.bank_id(self.batch[0])
            conn.execute('UPDATE bank_questions SET fingerprint_json=? WHERE id=?', ('{"checked":true}', bid))
            reveal(conn, bid, 'question', True); reveal(conn, bid, 'analysis', True)
        note = self.config.data/'memory'/'bank'/(bid+'.json'); note.parent.mkdir(parents=True); note.write_text('private note')
        with closing(sqlite3.connect(self.config.library_database)) as conn:
            before = conn.iterdump(); before = '\n'.join(before)
        assets = {p.relative_to(self.config.library_dir): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in self.config.library_dir.rglob('*.png')}
        plan = self.run_import(); self.assertEqual(plan['unchanged'], [bid])
        self.run_import(confirm=plan['plan_sha256'])
        with closing(sqlite3.connect(self.config.library_database)) as conn:
            self.assertEqual('\n'.join(conn.iterdump()), before)
        self.assertEqual(note.read_text(), 'private note')
        self.assertEqual({p.relative_to(self.config.library_dir): (p.read_bytes(), p.stat().st_mtime_ns)
                         for p in self.config.library_dir.rglob('*.png')}, assets)
        with Database(self.config).session() as conn:
            self.assertTrue(conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone())

    def test_revision_updates_stable_id_and_keeps_immutable_history(self):
        self.apply(); bid = records.bank_id(self.batch[0]); old_plan = self.run_import()
        self.batch[0]['revision'] = 'revision-2'
        self.batch[0]['analysis'] = records.resource('new reference')
        self.save()
        with self.assertRaisesRegex(ValueError, 'Preview changed'):
            self.run_import(confirm=old_plan['plan_sha256'])
        plan = self.run_import(); self.assertEqual(plan['updated'], [bid]); self.apply()
        with closing(sqlite3.connect(self.config.library_database)) as conn:
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_questions').fetchone()[0], 1)
            self.assertEqual(conn.execute('SELECT count(*) FROM bank_source_versions').fetchone()[0], 2)

    def test_identity_overlap_duplicates_and_database_changes_invalidate_confirmation(self):
        self.apply(); self.batch = [question('second')]; self.save()
        plan = self.run_import()
        self.assertEqual(len(plan['identity_conflicts']), 1)
        self.assertEqual(len(plan['duplicate_candidates']), 1)
        with closing(sqlite3.connect(self.config.library_database)) as conn, conn:
            conn.execute('UPDATE bank_questions SET fingerprint_json=?', ('{"new":true}',))
        with self.assertRaisesRegex(ValueError, 'Preview changed'):
            self.run_import(confirm=plan['plan_sha256'])
        self.apply()

    def test_cxy_converter_only_reads_explicit_exam_labels_and_preserves_original(self):
        def q(uid, label):
            return dict(id=uid, source=label, original_source=label, source_details=label, question_type='subjective',
                        stem='fixture', correct_answer='answer', answer_explanation='explanation', options=[])
        raw = {'questions':[q(1,'2026年·数一三（一22、三22）'), q(2,'2026年·数一'),
                            q(3,'2026小侯七四套卷·数一·第二套·第4题')], 'assetMap':{}}
        result = convert(raw, revision='fixture', source_sha256='0'*64)
        self.assertEqual([r['number'] for r in result], [22, None])
        self.assertIsNone(result[0]['question_type'])
        self.assertIsNone(result[0]['max_score'])
        self.assertEqual(result[0]['original']['record'], raw['questions'][0])

    def test_later_source_shares_exam_protection_and_exposure_but_not_annotations(self):
        from app.bank.access import access, aliases, policy_group, reveal, save_preferences
        self.apply(); Database(self.config).initialize()
        first = records.bank_id(self.batch[0])
        with Database(self.config).session(write=True) as conn:
            self.assertFalse(access(conn, first)['can_view'])
            reveal(conn, first, 'question', True); reveal(conn, first, 'analysis', True)
        self.batch = [question('other-source', source='S03')]; self.save()
        plan = import_source(self.config, 'S03', self.path, collection='other')
        import_source(self.config, 'S03', self.path, collection='other', confirm=plan['plan_sha256'])
        second = records.bank_id(self.batch[0])
        with Database(self.config).session(write=True) as conn:
            self.assertEqual(aliases(conn, first), {first})
            self.assertEqual(policy_group(conn, second), {first, second})
            self.assertTrue(access(conn, second)['analysis_allowed'])
            save_preferences(conn, dict(study_type=1, reserved=[dict(math_type=1, year='2026')]))
            self.assertTrue(access(conn, second)['reserved'])
            with self.assertRaisesRegex(ValueError, '预留'):reveal(conn, second, 'question', True)

    def test_source_selection_is_stable_and_conflicting_metadata_stays_unknown(self):
        from app.bank.exam_identity import select
        self.apply(); Database(self.config).initialize()
        first = records.bank_id(self.batch[0])
        self.batch = [question('other-source', source='S03')]
        self.batch[0].update(question_type='fill', max_score=12); self.save()
        plan = import_source(self.config, 'S03', self.path, collection='other')
        import_source(self.config, 'S03', self.path, collection='other', confirm=plan['plan_sha256'])
        with Database(self.config).session() as conn:
            self.assertEqual(select(conn, '2026', 1, 1), dict(matched_bank_id=first, question_type=None, max_score=None))
            self.assertEqual(select(conn, '2027', 1, 1), dict(matched_bank_id=None, question_type=None, max_score=None))

    def test_partial_identity_keeps_whole_paper_protection_without_exact_matching(self):
        from app.bank.access import access, save_preferences
        from app.bank.exam_identity import select
        self.batch=[question(number=None)];self.save()
        plan=self.run_import()
        self.assertIn('complete_exam_identity',plan['missing_fields'][0]['fields'])
        self.apply();Database(self.config).initialize()
        with Database(self.config).session(write=True) as conn:
            save_preferences(conn,dict(study_type=1,reserved=[dict(math_type=1,year='2026')]))
            self.assertTrue(access(conn,records.bank_id(self.batch[0]))['reserved'])
            self.assertIsNone(select(conn,'2026',1,1)['matched_bank_id'])

    def test_text_reading_records_exposure_only_on_actual_public_read(self):
        from app.agent.tools import execute
        from app.bank.access import access, public_bank, reveal
        from app.services.resources import ResourceService
        self.apply(); Database(self.config).initialize(); bid = records.bank_id(self.batch[0])
        value = json.loads(execute(self.root, self.config.data, 'read_bank', {'bank_id':bid})[0]['text'])
        self.assertIn('A. $2$', value['text'])
        self.assertTrue(value['internal_only'])
        with Database(self.config).session() as conn:
            self.assertFalse(conn.execute('SELECT 1 FROM bank_views').fetchone())
            library = public_bank(conn, bid, view='library')
            self.assertIn('question_text', library)
            self.assertNotIn('analysis_text', library)
            self.assertNotIn('analysis_image', library)
            self.assertNotIn('question_image', library)
        service = ResourceService(self.config, Database(self.config))
        body = json.loads(service.bank(bid, 'analysis', library=True).content)
        self.assertEqual(body['text'], '$1+1=2$')
        with Database(self.config).session() as conn:
            self.assertTrue(conn.execute('SELECT 1 FROM bank_exposures WHERE bank_id=?',(bid,)).fetchone())
            self.assertFalse(access(conn, bid)['can_view'])

    def test_text_frozen_snapshot_keeps_selected_content_after_reimport(self):
        from app.bank.annotations import materials
        from app.knowledge.catalog import digest
        from app.storage.practice_materials import freeze, load
        self.apply(); Database(self.config).initialize(); bid=records.bank_id(self.batch[0])
        with Database(self.config).session() as conn:
            actual=materials(conn,self.config.data,bid)
            binding=freeze(conn,self.config.data,dict(bank_id=bid,material_revision=digest(actual),
                                                     content_revision=actual['question']['sha256']))
        self.batch[0]['stem']=records.resource('changed current question');self.save();self.apply()
        saved=load(self.config.data,binding['snapshot_key'],binding['snapshot_sha256'])
        self.assertIn('Invented fixture',saved['resources']['question']['text'])
        self.assertIsNone(saved['resources']['question']['image_file'])

    def test_multiple_images_are_preserved_and_all_enter_the_readable_material(self):
        from PIL import Image
        self.batch[0]['stem'] = records.resource('')
        for name, color in [('first.png','red'),('second.png','blue')]:
            path=self.root/name;Image.new('RGB',(10,12),color).save(path)
            self.batch[0]['stem']['images'].append(dict(path=name,sha256=records.sha256(path.read_bytes()),media_type='image/png'))
        self.save();self.apply()
        with closing(sqlite3.connect(self.config.library_database)) as conn:
            paths=conn.execute('SELECT question_path,metadata_json FROM bank_resources').fetchone()
        with Image.open(self.config.library_dir/paths[0]) as image:
            self.assertEqual(image.size,(10,24))
            self.assertEqual(image.getpixel((0,0)),(255,0,0))
            self.assertEqual(image.getpixel((0,23)),(0,0,255))
        manifest=json.loads(paths[1])['resources']['question']
        self.assertEqual(len(manifest['images']),2)
        self.assertTrue(all((self.config.library_dir/i['path']).is_file() for i in manifest['images']))


class SourceAnnotationImportTests(unittest.TestCase):
    def test_reimport_preserves_ready_annotation_and_material_update_invalidates_it(self):
        from test_question_annotations import QuestionPreparationTests
        from app.bank import annotations
        from app.learning.tasks import finish_task
        f=QuestionPreparationTests();f.setUp();self.addCleanup(f.tearDown)
        f.prepare_catalog()
        record=question();record.update(stem=records.resource('求 f(x)=sin(x²) 的导数。'),
            options=[],answer=records.resource('2x cos(x²)'),analysis=records.resource('外层sin求导，再乘内层x²的导数2x。'))
        path=f.data/'source-fixture.jsonl'
        def save():path.write_text(records.canonical(record),encoding='utf8')
        def apply():
            plan=import_source(f.f.config,'S02',path,collection='zhenti')
            return import_source(f.f.config,'S02',path,collection='zhenti',confirm=plan['plan_sha256'])
        save();apply();bid=records.bank_id(record)
        f.start('annotate_questions',{'bank_ids':[bid]});f.read_annotation_material()
        f.tool('apply_report',{'result':f.envelope(f.annotation_result())})
        finish_task(f.conn,f.task['id']);f.conn.commit()
        original=annotations.current(f.conn,f.data,bid)
        self.assertEqual(original['analysis']['status'],'ready')
        before={name:[tuple(r) for r in f.conn.execute('SELECT * FROM '+name)] for name in
                ('bank_questions','bank_resources','question_annotations','question_annotation_links','question_annotation_topics')}
        self.assertEqual(apply()['unchanged'],[bid])
        self.assertEqual(before,{name:[tuple(r) for r in f.conn.execute('SELECT * FROM '+name)] for name in before})
        self.assertEqual(annotations.current(f.conn,f.data,bid)['id'],original['id'])
        record['analysis']=records.resource('A changed reference version');save();apply()
        self.assertIsNone(annotations.current(f.conn,f.data,bid))
        self.assertEqual(f.conn.execute('SELECT count(*) FROM question_annotations').fetchone()[0],1)


if __name__ == '__main__':unittest.main()
