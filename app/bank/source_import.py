"""The single preview/confirm entry point for standard source records.

Preview opens only the common library in read-only mode. Import owns one
library transaction and never initializes or writes the personal workspace.
"""
from contextlib import closing, contextmanager, ExitStack
import json
from pathlib import Path
import sqlite3

from app.bank import source_records as records
from app.common import now_iso


@contextmanager
def library(config, *, write=False):
    path = config.library_database.resolve()
    if not path.exists() and not write:
        conn = sqlite3.connect(':memory:')
    else:
        if write:
            path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(path.as_uri() + ('?mode=rwc' if write else '?mode=ro'), uri=True, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
    finally:
        conn.close()


def _tables(conn):
    from app.storage.boundaries import schema_rows
    return {r['name'] for r in schema_rows(conn)}


def _state(conn):
    tables = _tables(conn)
    return {name: [dict(r) for r in conn.execute('SELECT * FROM ' + name + ' ORDER BY 1')]
            for name in ('bank_questions', 'bank_resources', 'bank_identity', 'bank_source_records') if name in tables}


def preview(conn, batch, corrections, applied, excluded, collection, *, bank_ids=None, baselines=None):
    from app.bank.collections import require
    require(conn,collection)
    state = _state(conn)
    current = {r['bank_id']: r for r in state.get('bank_source_records', [])}
    for bid,baseline in (baselines or {}).items():
        if bid not in current:current[bid]=dict(bank_id=bid,record_json=records.canonical(baseline),record_sha256=records.digest([baseline,[]]))
    questions = {r['id']: r for r in state.get('bank_questions', [])}
    identities = {r['bank_id']: (str(r['year']), r['math_type'], r['number']) for r in state.get('bank_identity', [])}
    excluded_ids = {r['source_uid'] for r in excluded}
    report = dict(source_id=batch[0]['source_id'], revision=batch[0]['revision'], added=[], updated=[], unchanged=[],
                  missing_fields=[], identity_conflicts=[], duplicate_candidates=[], excluded=excluded,
                  overrides_applied=applied, errata_applied=[],invalidated_annotations=[],needs_annotation=[],metadata_only=[],collection_id=collection,collection_conflicts=[])
    content_groups = {}
    for row in current.values():
        old = json.loads(row['record_json'])
        content_groups.setdefault(records.digest([old['stem'], old['options']]), set()).add(row['bank_id'])
    for record in batch:
        if record['source_uid'] in excluded_ids:
            report['duplicate_candidates'].append(dict(bank_ids=[records.bank_id(record)],
                source_uid=record['source_uid'], reason='excluded_pending_candidate'))
            continue
        bid = (bank_ids or {}).get((record['source_id'],record['source_uid']), records.bank_id(record))
        old = current.get(bid)
        report['errata_applied'].extend(dict(bank_id=bid,**e,original_fragment=e['find'],new_fragment=e['replace']) for e in record.get('errata',[]))
        if bid in questions:
            stored=questions[bid].get('collection_id')
            if stored is None:
                from app.bank.collections import initial
                stored=initial(questions[bid],json.loads(old['record_json']) if old else None)
            if stored!=collection:report['collection_conflicts'].append(dict(bank_id=bid,existing=stored,requested=collection))
        if bid in questions and not old:
            raise ValueError('Bank ID collision with an unmanaged record: ' + bid)
        changes = [v for v in applied if v['source_uid'] == record['source_uid']]
        sha = records.digest([record, changes])
        category = 'added' if not old else 'unchanged' if old['record_sha256'] == sha else 'updated'
        report[category].append(bid)
        from app.bank.book_numbers import number_only
        metadata_only=category=='updated' and number_only(old,record,changes)
        if metadata_only:report['metadata_only'].append(bid)
        if category=='updated' and old and any(json.loads(old['record_json'])[r]!=record[r] for r in ('stem','options','answer','analysis')):
            if any(table in _tables(conn) and conn.execute('SELECT 1 FROM '+table+' WHERE bank_id=?',(bid,)).fetchone() for table in ('question_annotation_links','imported_question_annotations')):report['invalidated_annotations'].append(bid)
            if 'question_annotations' in _tables(conn):
                report['invalidated_annotations'].extend(r[0] for r in conn.execute('SELECT l.bank_id FROM question_annotation_links l JOIN question_annotations a ON a.id=l.annotation_id WHERE a.bank_id=?',(bid,)))
        if category in ('added', 'updated') and not metadata_only:
            report['needs_annotation'].append(bid)
        missing = [key for key in ('question_type', 'max_score') if record[key] is None]
        missing += [key for key in ('answer', 'analysis') if not record[key]['text'].strip() and not record[key]['images']]
        if any(record[k] is not None for k in records.IDENTITY) and not all(record[k] is not None for k in records.IDENTITY):
            missing.append('complete_exam_identity')
        if missing:
            report['missing_fields'].append(dict(bank_id=bid, source_uid=record['source_uid'], fields=missing))
        if all(record[k] is not None for k in records.IDENTITY):
            identity = (str(record['exam_year']), record['math_type'], record['number'])
            overlap = sorted(other for other, value in identities.items() if value == identity and other != bid)
            if overlap:
                report['identity_conflicts'].append(dict(bank_id=bid, exam_year=record['exam_year'],
                    math_type=record['math_type'], number=record['number'], existing_or_batch_bank_ids=overlap))
            identities[bid] = identity
        key = records.digest([record['stem'], record['options']])
        content_groups.setdefault(key, set()).add(bid)
        if not record['number'] and record['exam_year']:
            report['duplicate_candidates'].append(dict(bank_ids=[bid], reason='unnumbered_exam_candidate'))
    for ids in content_groups.values():
        if len(ids) > 1 and any(b in report['added'] + report['updated'] + report['unchanged'] for b in ids):
            report['duplicate_candidates'].append(dict(bank_ids=sorted(ids), reason='identical_stem_and_options'))
    report['invalidated_annotations']=sorted(set(report['invalidated_annotations']))
    report['plan_sha256'] = records.digest(dict(batch=batch, corrections=corrections, state=state, report=report))
    return report


def _copy_assets(record, asset_root, library_root):
    manifest = {}
    extension = {'image/png': '.png', 'image/jpeg': '.jpg', 'image/webp': '.webp'}
    for role in ('stem', 'answer', 'analysis'):
        source_parts = [record[role]] + ([o['content'] for o in record['options']] if role == 'stem' else [])
        images = []
        for part in source_parts:
            for image in part['images']:
                data = records.asset_path(asset_root, image['path']).read_bytes()
                if records.sha256(data) != image['sha256']:
                    raise ValueError('Asset changed after preview: ' + image['path'])
                relative = 'bank-assets/source/' + image['sha256'] + extension[image['media_type']]
                target = library_root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if target.exists():
                    if records.sha256(target.read_bytes()) != image['sha256']:
                        raise ValueError('Existing content-addressed asset is corrupt: ' + relative)
                else:
                    # Content-addressed immutable files may remain after a rollback;
                    # no row points at them until the transaction commits.
                    with target.open('xb') as output:
                        output.write(data)
                images.append(dict(image, path=relative))
        item = dict(text=records.display(record, role), images=images)
        if len(images) > 1:
            # Existing read/frozen-material contracts have one image per role.
            # Preserve originals and concatenate only the display derivative.
            from io import BytesIO
            from PIL import Image
            with ExitStack() as stack:
                originals = [stack.enter_context(Image.open(library_root / i['path'])).convert('RGB') for i in images]
                canvas = Image.new('RGB', (max(i.width for i in originals), sum(i.height for i in originals)), 'white')
                y = 0
                for image in originals:
                    canvas.paste(image, (0, y)); y += image.height
                raw = BytesIO(); canvas.save(raw, format='PNG'); data = raw.getvalue()
            sha = records.sha256(data)
            relative = 'bank-assets/source/' + sha + '.png'
            target = library_root / relative
            if target.exists() and records.sha256(target.read_bytes()) != sha:
                raise ValueError('Corrupt display derivative: ' + relative)
            if not target.exists():
                with target.open('xb') as output:output.write(data)
            item['display_image'] = dict(path=relative, sha256=sha, media_type='image/png')
        manifest['question' if role == 'stem' else role] = item
    return manifest


def _apply(conn, config, batch, report, asset_root, *, bank_ids=None, initialize_schema=True):
    if initialize_schema:
        from app.storage.boundaries import LIBRARY_TABLES
        from app.storage.split import template, copy_schema
        with closing(template()) as schema:
            copy_schema(schema, conn, LIBRARY_TABLES)
        from app.storage.library_identity import initialize
        initialize(conn)
        from app.bank.collections import initialize as collections
        collections(conn)
        from app.bank.applicability import initialize as applicability
        applicability(conn)
        from app.storage.navigation_index import initialize as navigation
        navigation(conn)
    excluded = {r['source_uid'] for r in report['excluded']}
    for record in batch:
        bid = (bank_ids or {}).get((record['source_id'],record['source_uid']), records.bank_id(record))
        if record['source_uid'] in excluded or bid in report['unchanged']:
            continue
        if bid in report.get('metadata_only',[]):
            old=conn.execute('SELECT metadata_json FROM bank_resources WHERE bank_id=?',(bid,)).fetchone()
            metadata=json.loads(old[0]);metadata['book']={**metadata.get('book',{}),'number':record['book']['number']}
            changes=[v for v in report['overrides_applied'] if v['source_uid']==record['source_uid']]
            sha=records.digest([record,changes]);text=records.canonical(record);audit=records.canonical(changes)
            conn.execute('UPDATE bank_resources SET metadata_json=? WHERE bank_id=?',(records.canonical(metadata),bid))
            conn.execute('UPDATE bank_source_records SET record_json=?,record_sha256=?,overrides_json=? WHERE bank_id=?',(text,sha,audit,bid))
            conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',(bid,sha,text,audit,now_iso()))
            continue
        manifest = _copy_assets(record, asset_root, config.library_dir)
        metadata = {k: record[k] for k in ('schema', 'source_id', 'revision', 'source_uid', *records.METADATA)}
        metadata.update(locator=record['locator'], original_source=record['original']['source_text'], resources=manifest)
        if 'book' in record:metadata['book']=record['book']
        if 'errata' in record:metadata['errata']=record['errata']
        changes = [v for v in report['overrides_applied'] if v['source_uid'] == record['source_uid']]
        sha = records.digest([record, changes])
        conn.execute('''INSERT INTO bank_questions(id,source,source_ref,stem,answer,explanation,tags_json,created_at)
            VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET source=excluded.source,source_ref=excluded.source_ref,
            stem=excluded.stem,answer=excluded.answer,explanation=excluded.explanation,tags_json=excluded.tags_json''',
            (bid, record['source_id'], record['source_uid'], manifest['question']['text'], manifest['answer']['text'],
             manifest['analysis']['text'], records.canonical(record['tags']), now_iso()))
        conn.execute('UPDATE bank_questions SET collection_id=? WHERE id=?',(report['collection_id'],bid))
        conn.execute('UPDATE bank_questions SET math_types_json=? WHERE id=?',(records.canonical(record.get('math_types',[record['math_type']] if record['math_type'] in (1,2,3) else [])),bid))
        paths = [manifest[r].get('display_image', manifest[r]['images'][0])['path'] if manifest[r]['images'] else ''
                 for r in ('question', 'analysis', 'answer')]
        conn.execute('''INSERT INTO bank_resources VALUES(?,?,?,?,?) ON CONFLICT(bank_id) DO UPDATE SET
            metadata_json=excluded.metadata_json,question_path=excluded.question_path,
            analysis_path=excluded.analysis_path,answer_path=excluded.answer_path''', (bid, records.canonical(metadata), *paths))
        # Keep known year/category for whole-paper protection even without a
        # number; only complete triples participate in exact exam matching.
        identity = (record['math_type'] or 0, str(record['exam_year']) if record['exam_year'] else '', record['number'] or 0)
        conn.execute('''INSERT INTO bank_identity VALUES(?,?,?,?,NULL) ON CONFLICT(bank_id) DO UPDATE SET
            math_type=excluded.math_type,year=excluded.year,number=excluded.number,sha256=NULL''', (bid, *identity))
        conn.execute('''INSERT INTO bank_source_records VALUES(?,?,?,?,?,?,?) ON CONFLICT(bank_id) DO UPDATE SET
            revision=excluded.revision,record_sha256=excluded.record_sha256,record_json=excluded.record_json,
            overrides_json=excluded.overrides_json''',
            (bid, record['source_id'], record['source_uid'], record['revision'], sha, records.canonical(record), records.canonical(changes)))
        conn.execute('INSERT OR IGNORE INTO bank_source_versions VALUES(?,?,?,?,?)',
                     (bid, sha, records.canonical(record), records.canonical(changes), now_iso()))


def import_source(config, source_id, input_path, *, collection, asset_root=None, overrides=None, errata=None, confirm=None):
    asset_root = Path(asset_root or Path(input_path).parent)
    batch, corrections, applied, excluded = records.load(input_path, source_id, asset_root, overrides,errata)
    with library(config) as conn:
        conn.execute('BEGIN')
        report = preview(conn, batch, corrections, applied, excluded,collection)
    if confirm is None:
        return dict(report, applied=False)
    if confirm != report['plan_sha256']:
        raise ValueError('Preview changed; rerun --dry-run and confirm the new plan_sha256')
    if report['collection_conflicts']:raise ValueError('Collection conflict: existing questions cannot change collection')
    with library(config, write=True) as conn:
        conn.execute('BEGIN IMMEDIATE')
        try:
            locked = preview(conn, batch, corrections, applied, excluded,collection)
            if locked['plan_sha256'] != confirm:
                raise ValueError('Library changed after preview; rerun --dry-run')
            _apply(conn, config, batch, report, asset_root)
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
    return dict(report, applied=True)
